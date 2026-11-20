"""The Git Provider Interface.

Every Git host (GitHub first, GitLab/Bitbucket later) is exposed to the
rest of the platform through this interface, mirroring the Common Agent
Runtime Interface (`app/services/agent_runtime/base.py`): a new provider
means a new adapter class, never a change to the routes or sync logic
that call it. An adapter never claims a repository is reachable or a
commit is real without having actually asked the provider -- a
misconfigured or unreachable provider reports `connected=False` /
raises `GitProviderError` with the real detail, never a fabricated
success.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


class GitProviderError(Exception):
    """Raised when a real call to the provider's API fails. `detail` is
    the real, specific reason -- never a generic 'something went wrong'."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class GitHealthCheckResult:
    connected: bool
    account_login: str = ""
    detail: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class RepositorySummary:
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool


@dataclass(frozen=True)
class CommitSummary:
    sha: str
    message: str = ""


@dataclass(frozen=True)
class PullRequestSummary:
    number: int
    url: str
    state: str = "open"


@dataclass(frozen=True)
class BranchProtectionSummary:
    """What the provider's own branch protection rules require for a
    branch -- `protected=False` means GitHub reports no rules configured,
    never a guess from an unrelated failure (see `get_branch_protection`)."""

    protected: bool
    required_status_checks: list[str] = field(default_factory=list)
    required_approving_review_count: int = 0


class GitProviderAdapter(ABC):
    """Base class every Git provider adapter implements."""

    slug: str
    display_name: str

    @abstractmethod
    def health_check(self, external_installation_id: str) -> GitHealthCheckResult:
        """A real check that this installation's credentials can currently
        reach the provider's API. Must never return `connected=True`
        without having actually observed a successful call."""

    @abstractmethod
    def list_repositories(self, external_installation_id: str) -> list[RepositorySummary]:
        """The real set of repositories this installation currently grants
        access to. Raises `GitProviderError` on any failure -- never
        returns a fabricated or stale list."""

    @abstractmethod
    def get_repository(self, external_installation_id: str, owner: str, name: str) -> RepositorySummary:
        """The real, current metadata for one repository."""

    @abstractmethod
    def get_branch_head_commit(
        self, external_installation_id: str, owner: str, name: str, branch: str
    ) -> CommitSummary:
        """The real current HEAD commit of one branch."""

    @abstractmethod
    def get_authenticated_clone_url(self, external_installation_id: str, owner: str, name: str) -> str:
        """A real HTTPS clone URL with a short-lived, real credential
        embedded, usable directly with `git clone` -- never a long-lived
        personal access token. Raises `GitProviderError` with the real
        reason if a credential cannot be obtained."""

    @abstractmethod
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
        """Opens a real pull request from `head_branch` into `base_branch`
        via the provider's API. `head_branch` must already exist on the
        remote (push it first). Raises `GitProviderError` with the real
        reason on failure -- never a fabricated PR number or URL."""

    @abstractmethod
    def get_branch_protection(
        self, external_installation_id: str, owner: str, name: str, branch: str
    ) -> BranchProtectionSummary:
        """The real branch protection rules GitHub has configured for
        `branch`, if any. A branch with no rules configured is a real,
        successful result (`protected=False`), not an error. Raises
        `GitProviderError` only when the check itself could not be made."""
