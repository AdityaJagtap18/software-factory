from app.services.git_provider.base import GitProviderAdapter
from app.services.git_provider.github_app import GitHubAppAdapter

_PROVIDERS: dict[str, GitProviderAdapter] = {
    adapter.slug: adapter for adapter in (GitHubAppAdapter(),)
}


def all_git_providers() -> list[GitProviderAdapter]:
    return list(_PROVIDERS.values())


def get_git_provider(slug: str) -> GitProviderAdapter | None:
    return _PROVIDERS.get(slug)
