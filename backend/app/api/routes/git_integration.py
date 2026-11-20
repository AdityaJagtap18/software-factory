import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import (
    ProjectContext,
    get_current_user,
    require_org_admin,
    require_org_member,
    require_project_access,
)
from app.core.database import get_db
from app.models.git_integration import (
    GitInstallation,
    GitProvider,
    InstallationStatus,
    RepositoryConnection,
    RepositoryConnectionStatus,
)
from app.models.organization import OrganizationMember
from app.models.project import ProjectRole
from app.models.user import User
from app.schemas.git_integration import (
    BranchComparisonSchema,
    BranchCreate,
    BranchSummarySchema,
    GitInstallationCreate,
    GitInstallationResponse,
    RepositoryConnectionCreate,
    RepositoryConnectionResponse,
    RepositoryCreate,
    RepositorySummarySchema,
    WebhookEventResponse,
)
from app.services import audit, git_sync, git_webhook
from app.services.git_provider.base import GitProviderError
from app.services.git_provider.registry import get_git_provider

router = APIRouter(tags=["git-integration"])


def _run_installation_health_check(installation: GitInstallation) -> None:
    adapter = get_git_provider(installation.provider.value)
    result = adapter.health_check(installation.external_installation_id) if adapter else None
    if result is None:
        installation.status = InstallationStatus.NOT_CONNECTED
        installation.last_error = f"Unknown git provider '{installation.provider.value}'."
    else:
        installation.status = (
            InstallationStatus.CONNECTED if result.connected else InstallationStatus.NOT_CONNECTED
        )
        installation.last_error = "" if result.connected else result.detail
        if result.account_login:
            installation.account_login = result.account_login
    installation.last_health_check_at = datetime.now(timezone.utc)


@router.post(
    "/organizations/{organization_id}/git-installations",
    response_model=GitInstallationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_installation(
    organization_id: uuid.UUID,
    payload: GitInstallationCreate,
    admin_membership: OrganizationMember = Depends(require_org_admin),
    db: DBSession = Depends(get_db),
) -> GitInstallationResponse:
    """Records a completed GitHub App installation -- the installation
    itself happens on GitHub (an admin installs the app on their account
    or organization); this endpoint stores the resulting installation id
    GitHub hands back, exactly as FR-201 requires, and immediately runs a
    real health check against it."""
    existing = (
        db.query(GitInstallation)
        .filter_by(
            organization_id=organization_id,
            provider=GitProvider.GITHUB,
            external_installation_id=payload.external_installation_id,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This installation is already connected")

    installation = GitInstallation(
        organization_id=organization_id,
        provider=GitProvider.GITHUB,
        external_installation_id=payload.external_installation_id,
        account_login=payload.account_login,
        created_by_user_id=admin_membership.user_id,
    )
    db.add(installation)
    db.flush()

    _run_installation_health_check(installation)

    audit.record(
        db,
        action="git_installation.create",
        target_type="git_installation",
        target_id=str(installation.id),
        actor_user_id=admin_membership.user_id,
        organization_id=organization_id,
        extra={"status": installation.status.value},
    )
    db.commit()
    db.refresh(installation)
    return installation


@router.get(
    "/organizations/{organization_id}/git-installations",
    response_model=list[GitInstallationResponse],
)
def list_installations(
    organization_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> list[GitInstallationResponse]:
    return (
        db.query(GitInstallation)
        .filter_by(organization_id=organization_id)
        .order_by(GitInstallation.created_at.desc())
        .all()
    )


@router.post(
    "/organizations/{organization_id}/git-installations/{installation_id}/health-check",
    response_model=GitInstallationResponse,
)
def recheck_installation(
    organization_id: uuid.UUID,
    installation_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> GitInstallationResponse:
    installation = db.get(GitInstallation, installation_id)
    if installation is None or installation.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Installation not found")

    _run_installation_health_check(installation)
    audit.record(
        db,
        action="git_installation.health_check",
        target_type="git_installation",
        target_id=str(installation.id),
        actor_user_id=membership.user_id,
        organization_id=organization_id,
        extra={"status": installation.status.value},
    )
    db.commit()
    db.refresh(installation)
    return installation


@router.delete(
    "/organizations/{organization_id}/git-installations/{installation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_installation(
    organization_id: uuid.UUID,
    installation_id: uuid.UUID,
    admin_membership: OrganizationMember = Depends(require_org_admin),
    db: DBSession = Depends(get_db),
) -> None:
    """Revokes this org's installation. Cascades to every repository
    connection scoped under it (§21.1): without the installation, those
    connections have no real way to reach the repository anyway."""
    installation = db.get(GitInstallation, installation_id)
    if installation is None or installation.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Installation not found")

    audit.record(
        db,
        action="git_installation.revoke",
        target_type="git_installation",
        target_id=str(installation.id),
        actor_user_id=admin_membership.user_id,
        organization_id=organization_id,
        extra={"external_installation_id": installation.external_installation_id},
    )
    db.delete(installation)
    db.commit()


@router.get(
    "/organizations/{organization_id}/git-installations/{installation_id}/repositories",
    response_model=list[RepositorySummarySchema],
)
def list_installation_repositories(
    organization_id: uuid.UUID,
    installation_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> list[RepositorySummarySchema]:
    installation = db.get(GitInstallation, installation_id)
    if installation is None or installation.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Installation not found")

    adapter = get_git_provider(installation.provider.value)
    if adapter is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown git provider")
    try:
        repos = adapter.list_repositories(installation.external_installation_id)
    except GitProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.detail) from exc
    return [RepositorySummarySchema(**vars(r)) for r in repos]


def _get_repository_connection_or_404(
    db: DBSession, project_id: uuid.UUID, connection_id: uuid.UUID
) -> RepositoryConnection:
    connection = db.get(RepositoryConnection, connection_id)
    if connection is None or connection.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository connection not found")
    return connection


@router.post(
    "/projects/{project_id}/repository-connections",
    response_model=RepositoryConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_repository_connection(
    project_id: uuid.UUID,
    payload: RepositoryConnectionCreate,
    ctx: ProjectContext = Depends(require_project_access),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> RepositoryConnectionResponse:
    """Connects one real, discovered repository to this project. The
    installation must belong to this project's own organization -- a
    repository is never resolved from a bare owner/name supplied without
    an authorized installation behind it (§21.1/§21.5)."""
    ctx.require_role({ProjectRole.PROJECT_ADMIN})

    installation = db.get(GitInstallation, payload.git_installation_id)
    if installation is None or installation.organization_id != ctx.project.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Installation not found for this organization")

    full_name = f"{payload.owner}/{payload.name}"
    existing = (
        db.query(RepositoryConnection).filter_by(project_id=project_id, full_name=full_name).first()
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This repository is already connected to this project")

    connection = RepositoryConnection(
        project_id=project_id,
        git_installation_id=installation.id,
        owner=payload.owner,
        name=payload.name,
        full_name=full_name,
        selected_working_branches=payload.selected_working_branches,
        created_by_user_id=user.id,
    )
    connection.installation = installation
    db.add(connection)
    db.flush()

    git_sync.sync_repository_connection(connection)

    audit.record(
        db,
        action="repository_connection.create",
        target_type="repository_connection",
        target_id=str(connection.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
        extra={"full_name": full_name, "status": connection.status.value},
    )
    db.commit()
    db.refresh(connection)
    return connection


@router.get(
    "/projects/{project_id}/repository-connections",
    response_model=list[RepositoryConnectionResponse],
)
def list_repository_connections(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[RepositoryConnectionResponse]:
    return (
        db.query(RepositoryConnection)
        .filter_by(project_id=project_id)
        .order_by(RepositoryConnection.created_at.desc())
        .all()
    )


@router.delete(
    "/projects/{project_id}/repository-connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_repository_connection(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> None:
    ctx.require_role({ProjectRole.PROJECT_ADMIN})
    connection = _get_repository_connection_or_404(db, project_id, connection_id)
    db.delete(connection)
    db.commit()


@router.post(
    "/projects/{project_id}/repository-connections/{connection_id}/sync",
    response_model=RepositoryConnectionResponse,
)
def sync_repository_connection_now(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> RepositoryConnectionResponse:
    """The manual synchronization recovery action FR-203 requires -- the
    same real sync logic a webhook triggers, runnable on demand."""
    connection = _get_repository_connection_or_404(db, project_id, connection_id)
    git_sync.sync_repository_connection(connection)
    db.commit()
    db.refresh(connection)
    return connection


@router.get(
    "/projects/{project_id}/repository-connections/{connection_id}/branches",
    response_model=list[BranchSummarySchema],
)
def list_connection_branches(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[BranchSummarySchema]:
    connection = _get_repository_connection_or_404(db, project_id, connection_id)
    adapter = get_git_provider(connection.installation.provider.value)
    if adapter is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown git provider")
    try:
        branches = adapter.list_branches(
            connection.installation.external_installation_id, connection.owner, connection.name
        )
    except GitProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.detail) from exc
    return [BranchSummarySchema(**vars(b)) for b in branches]


@router.post(
    "/projects/{project_id}/repository-connections/{connection_id}/branches",
    response_model=BranchSummarySchema,
    status_code=status.HTTP_201_CREATED,
)
def create_connection_branch(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    payload: BranchCreate,
    ctx: ProjectContext = Depends(require_project_access),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> BranchSummarySchema:
    ctx.require_role({ProjectRole.PROJECT_ADMIN, ProjectRole.DEVELOPER})
    connection = _get_repository_connection_or_404(db, project_id, connection_id)
    adapter = get_git_provider(connection.installation.provider.value)
    if adapter is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown git provider")
    from_branch = payload.from_branch or connection.default_branch
    if not from_branch:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No base branch known for this repository")
    try:
        branch = adapter.create_branch(
            connection.installation.external_installation_id,
            connection.owner,
            connection.name,
            payload.name,
            from_branch,
        )
    except GitProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.detail) from exc
    audit.record(
        db,
        action="repository_branch.create",
        target_type="repository_connection",
        target_id=str(connection.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
        extra={"branch": payload.name, "from_branch": from_branch},
    )
    db.commit()
    return BranchSummarySchema(**vars(branch))


@router.get(
    "/projects/{project_id}/repository-connections/{connection_id}/compare",
    response_model=BranchComparisonSchema,
)
def compare_connection_branches(
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    head: str,
    base: str = "",
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> BranchComparisonSchema:
    """Read-only: the real commits and diff of `head` against `base` (the
    repository's default branch when `base` is omitted), so a branch can
    be checked before deciding to merge it."""
    connection = _get_repository_connection_or_404(db, project_id, connection_id)
    adapter = get_git_provider(connection.installation.provider.value)
    if adapter is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown git provider")
    base_branch = base or connection.default_branch
    if not base_branch:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No base branch known for this repository")
    try:
        comparison = adapter.compare_branches(
            connection.installation.external_installation_id,
            connection.owner,
            connection.name,
            base_branch,
            head,
        )
    except GitProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.detail) from exc
    return BranchComparisonSchema(
        ahead_by=comparison.ahead_by,
        behind_by=comparison.behind_by,
        commits=[
            {
                "sha": c.sha,
                "message": c.message,
                "author_login": c.author_login,
                "authored_at": c.authored_at,
            }
            for c in comparison.commits
        ],
        diff_text=comparison.diff_text,
    )


@router.post(
    "/projects/{project_id}/repository-connections/create-repository",
    response_model=RepositoryConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_repository_and_connect(
    project_id: uuid.UUID,
    payload: RepositoryCreate,
    ctx: ProjectContext = Depends(require_project_access),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> RepositoryConnectionResponse:
    """Creates a real, brand-new repository on GitHub, then connects it to
    this project exactly as `create_repository_connection` would an
    existing one -- one step, same real sync logic."""
    ctx.require_role({ProjectRole.PROJECT_ADMIN})

    installation = db.get(GitInstallation, payload.git_installation_id)
    if installation is None or installation.organization_id != ctx.project.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Installation not found for this organization")

    adapter = get_git_provider(installation.provider.value)
    if adapter is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown git provider")
    try:
        created = adapter.create_repository(
            installation.external_installation_id, payload.name, payload.private
        )
    except GitProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.detail) from exc

    existing = (
        db.query(RepositoryConnection)
        .filter_by(project_id=project_id, full_name=created.full_name)
        .first()
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This repository is already connected to this project")

    connection = RepositoryConnection(
        project_id=project_id,
        git_installation_id=installation.id,
        owner=created.owner,
        name=created.name,
        full_name=created.full_name,
        selected_working_branches=payload.selected_working_branches,
        created_by_user_id=user.id,
    )
    connection.installation = installation
    db.add(connection)
    db.flush()

    git_sync.sync_repository_connection(connection)

    audit.record(
        db,
        action="repository_connection.create_repository",
        target_type="repository_connection",
        target_id=str(connection.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
        extra={"full_name": created.full_name, "status": connection.status.value},
    )
    db.commit()
    db.refresh(connection)
    return connection


@router.post("/webhooks/github", response_model=WebhookEventResponse)
async def receive_github_webhook(request: Request, db: DBSession = Depends(get_db)) -> WebhookEventResponse:
    """Signature-verified, idempotent GitHub webhook receiver. No auth
    dependency -- GitHub itself is the caller -- but every delivery's
    `X-Hub-Signature-256` is checked against this backend's own webhook
    secret before anything in the payload is trusted."""
    raw_body = await request.body()
    signature_header = request.headers.get("x-hub-signature-256")
    event_type = request.headers.get("x-github-event", "")
    delivery_id = request.headers.get("x-github-delivery", "")
    if not delivery_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing X-GitHub-Delivery header")

    signature_verified = git_webhook.verify_request_signature(raw_body, signature_header)
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except ValueError:
        payload = {}

    event = git_webhook.process_event(
        db,
        event_type=event_type,
        delivery_id=delivery_id,
        signature_verified=signature_verified,
        payload=payload,
    )
    if not signature_verified:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing webhook signature")
    return event
