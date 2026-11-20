"""The GitHub App adapter -- the first (and currently only) implementation
of the Git Provider Interface.

Authentication uses a GitHub App, never a long-lived personal access
token: this backend holds one platform-level App private key (in
settings) and mints short-lived, repository-scoped installation access
tokens on demand via GitHub's own `/app/installations/{id}/access_tokens`
endpoint. If no App is configured on this backend (`SF_GITHUB_APP_ID` /
`SF_GITHUB_APP_PRIVATE_KEY` unset -- true of the environment this was
built in), every call honestly reports `connected=False` / raises
`GitProviderError` with that real reason, exactly like every coding-agent
adapter's local-runtime/no-credential path (`app/services/agent_runtime`).
"""

import time

import httpx
import jwt

from app.core.config import get_settings
from app.services.git_provider.base import (
    CommitSummary,
    GitHealthCheckResult,
    GitProviderAdapter,
    GitProviderError,
    PullRequestSummary,
    RepositorySummary,
)

_PROBE_TIMEOUT_SECONDS = 10.0
_APP_JWT_LIFETIME_SECONDS = 540  # GitHub allows at most 10 minutes; stay under it.
_API_VERSION_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _app_configured() -> bool:
    settings = get_settings()
    return bool(settings.github_app_id and settings.github_app_private_key)


def _not_configured_detail() -> str:
    return (
        "GitHub App not configured on this backend "
        "(SF_GITHUB_APP_ID / SF_GITHUB_APP_PRIVATE_KEY missing)."
    )


def _build_app_jwt() -> str:
    """A real RS256 JWT signed with this backend's GitHub App private key,
    per GitHub's App authentication spec. Raised errors (a malformed key)
    are real, not swallowed."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + _APP_JWT_LIFETIME_SECONDS,
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, settings.github_app_private_key, algorithm="RS256")


def _mint_installation_token(external_installation_id: str) -> str:
    settings = get_settings()
    app_jwt = _build_app_jwt()
    try:
        resp = httpx.post(
            f"{settings.github_api_base_url}/app/installations/{external_installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}", **_API_VERSION_HEADERS},
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise GitProviderError(f"Could not reach GitHub: {exc}") from exc
    if resp.status_code != 201:
        raise GitProviderError(
            f"GitHub rejected the installation token request (HTTP {resp.status_code}): "
            f"{resp.text[:300]}"
        )
    token = resp.json().get("token")
    if not token:
        raise GitProviderError("GitHub returned no installation token.")
    return token


def _get_installation_account_login(external_installation_id: str) -> str:
    settings = get_settings()
    app_jwt = _build_app_jwt()
    try:
        resp = httpx.get(
            f"{settings.github_api_base_url}/app/installations/{external_installation_id}",
            headers={"Authorization": f"Bearer {app_jwt}", **_API_VERSION_HEADERS},
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise GitProviderError(f"Could not reach GitHub: {exc}") from exc
    if resp.status_code != 200:
        raise GitProviderError(
            f"GitHub rejected the installation lookup (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    return (resp.json().get("account") or {}).get("login", "")


def _repo_summary(data: dict) -> RepositorySummary:
    owner = (data.get("owner") or {}).get("login", "")
    return RepositorySummary(
        owner=owner,
        name=data.get("name", ""),
        full_name=data.get("full_name", f"{owner}/{data.get('name', '')}"),
        default_branch=data.get("default_branch", ""),
        private=bool(data.get("private", True)),
    )


class GitHubAppAdapter(GitProviderAdapter):
    slug = "github"
    display_name = "GitHub"

    def health_check(self, external_installation_id: str) -> GitHealthCheckResult:
        if not _app_configured():
            return GitHealthCheckResult(connected=False, detail=_not_configured_detail())
        try:
            account_login = _get_installation_account_login(external_installation_id)
            _mint_installation_token(external_installation_id)
        except GitProviderError as exc:
            return GitHealthCheckResult(connected=False, detail=exc.detail)
        return GitHealthCheckResult(
            connected=True,
            account_login=account_login,
            detail=f"Installation token minted for '{account_login}'.",
        )

    def list_repositories(self, external_installation_id: str) -> list[RepositorySummary]:
        if not _app_configured():
            raise GitProviderError(_not_configured_detail())
        settings = get_settings()
        token = _mint_installation_token(external_installation_id)
        repos: list[RepositorySummary] = []
        page = 1
        while True:
            try:
                resp = httpx.get(
                    f"{settings.github_api_base_url}/installation/repositories",
                    headers={"Authorization": f"Bearer {token}", **_API_VERSION_HEADERS},
                    params={"per_page": 100, "page": page},
                    timeout=_PROBE_TIMEOUT_SECONDS,
                )
            except httpx.HTTPError as exc:
                raise GitProviderError(f"Could not reach GitHub: {exc}") from exc
            if resp.status_code != 200:
                raise GitProviderError(
                    f"GitHub rejected the repository list request (HTTP {resp.status_code}): "
                    f"{resp.text[:300]}"
                )
            body = resp.json()
            page_repos = body.get("repositories", [])
            repos.extend(_repo_summary(r) for r in page_repos)
            if len(page_repos) < 100:
                break
            page += 1
        return repos

    def get_repository(self, external_installation_id: str, owner: str, name: str) -> RepositorySummary:
        if not _app_configured():
            raise GitProviderError(_not_configured_detail())
        settings = get_settings()
        token = _mint_installation_token(external_installation_id)
        try:
            resp = httpx.get(
                f"{settings.github_api_base_url}/repos/{owner}/{name}",
                headers={"Authorization": f"Bearer {token}", **_API_VERSION_HEADERS},
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise GitProviderError(f"Could not reach GitHub: {exc}") from exc
        if resp.status_code != 200:
            raise GitProviderError(
                f"GitHub rejected the repository lookup for '{owner}/{name}' "
                f"(HTTP {resp.status_code}): {resp.text[:300]}"
            )
        return _repo_summary(resp.json())

    def get_branch_head_commit(
        self, external_installation_id: str, owner: str, name: str, branch: str
    ) -> CommitSummary:
        if not _app_configured():
            raise GitProviderError(_not_configured_detail())
        settings = get_settings()
        token = _mint_installation_token(external_installation_id)
        try:
            resp = httpx.get(
                f"{settings.github_api_base_url}/repos/{owner}/{name}/branches/{branch}",
                headers={"Authorization": f"Bearer {token}", **_API_VERSION_HEADERS},
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise GitProviderError(f"Could not reach GitHub: {exc}") from exc
        if resp.status_code != 200:
            raise GitProviderError(
                f"GitHub rejected the branch lookup for '{owner}/{name}@{branch}' "
                f"(HTTP {resp.status_code}): {resp.text[:300]}"
            )
        data = resp.json()
        commit = data.get("commit") or {}
        message = ((commit.get("commit") or {}).get("message") or "")[:500]
        return CommitSummary(sha=commit.get("sha", ""), message=message)

    def get_authenticated_clone_url(self, external_installation_id: str, owner: str, name: str) -> str:
        if not _app_configured():
            raise GitProviderError(_not_configured_detail())
        settings = get_settings()
        token = _mint_installation_token(external_installation_id)
        host = settings.github_api_base_url.replace("https://api.", "https://").removesuffix("/")
        return f"https://x-access-token:{token}@{host.split('://', 1)[1]}/{owner}/{name}.git"

    def create_pull_request(
        self,
        external_installation_id: str,
        owner: str,
        name: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str = "",
    ) -> PullRequestSummary:
        if not _app_configured():
            raise GitProviderError(_not_configured_detail())
        settings = get_settings()
        token = _mint_installation_token(external_installation_id)
        try:
            resp = httpx.post(
                f"{settings.github_api_base_url}/repos/{owner}/{name}/pulls",
                headers={"Authorization": f"Bearer {token}", **_API_VERSION_HEADERS},
                json={"title": title, "head": head_branch, "base": base_branch, "body": body},
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise GitProviderError(f"Could not reach GitHub: {exc}") from exc
        if resp.status_code != 201:
            raise GitProviderError(
                f"GitHub rejected the pull request creation for '{owner}/{name}' "
                f"(HTTP {resp.status_code}): {resp.text[:300]}"
            )
        data = resp.json()
        return PullRequestSummary(number=data.get("number", 0), url=data.get("html_url", ""))
