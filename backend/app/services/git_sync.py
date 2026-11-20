"""Real repository metadata synchronization -- used both when a repository
connection is first created and by the manual "sync now" recovery action.
"""

from datetime import datetime, timezone

from app.models.git_integration import RepositoryConnection, RepositoryConnectionStatus
from app.services.git_provider.base import GitProviderError
from app.services.git_provider.registry import get_git_provider


def sync_repository_connection(connection: RepositoryConnection) -> None:
    """Mutates `connection` in place with the real current repository
    metadata. On any failure, the connection is marked `error` with the
    real reason -- its previously-known-good fields are left untouched
    rather than overwritten with something fabricated."""
    adapter = get_git_provider(connection.installation.provider.value)
    if adapter is None:
        connection.status = RepositoryConnectionStatus.ERROR
        connection.last_error = f"Unknown git provider '{connection.installation.provider.value}'."
        return

    try:
        repo = adapter.get_repository(
            connection.installation.external_installation_id, connection.owner, connection.name
        )
        branch = repo.default_branch or connection.default_branch
        commit = adapter.get_branch_head_commit(
            connection.installation.external_installation_id, connection.owner, connection.name, branch
        )
    except GitProviderError as exc:
        connection.status = RepositoryConnectionStatus.ERROR
        connection.last_error = exc.detail
        return

    connection.default_branch = repo.default_branch
    connection.last_observed_commit_sha = commit.sha
    connection.last_successful_sync_at = datetime.now(timezone.utc)
    connection.status = RepositoryConnectionStatus.CONNECTED
    connection.last_error = ""
