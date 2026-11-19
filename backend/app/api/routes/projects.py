import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import (
    ProjectContext,
    get_current_user,
    require_org_member,
    require_project_access,
)
from app.core.database import get_db
from app.models.organization import OrganizationMember
from app.models.project import Project, ProjectMember, ProjectRole, Workspace
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectMemberInvite,
    ProjectMemberResponse,
    ProjectMemberRoleUpdate,
    ProjectResponse,
    ProjectUpdate,
    WorkspaceCreate,
    WorkspaceResponse,
)
from app.services import audit
from app.services.slugify import slugify

router = APIRouter(tags=["projects"])

MANAGE_ROLES = {ProjectRole.PROJECT_ADMIN}


def _unique_slug(db: DBSession, organization_id: uuid.UUID, name: str) -> str:
    base = slugify(name)
    slug = base
    suffix = 1
    while (
        db.query(Project).filter_by(organization_id=organization_id, slug=slug).first()
        is not None
    ):
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


@router.post(
    "/organizations/{organization_id}/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    organization_id: uuid.UUID,
    payload: ProjectCreate,
    org_membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> ProjectResponse:
    project = Project(
        organization_id=organization_id,
        name=payload.name,
        slug=_unique_slug(db, organization_id, payload.name),
        description=payload.description,
        repository_url=payload.repository_url,
    )
    db.add(project)
    db.flush()

    db.add(
        ProjectMember(
            project_id=project.id, user_id=org_membership.user_id, role=ProjectRole.PROJECT_ADMIN
        )
    )
    audit.record(
        db,
        action="project.create",
        target_type="project",
        target_id=str(project.id),
        actor_user_id=org_membership.user_id,
        organization_id=organization_id,
    )
    db.commit()
    db.refresh(project)
    return ProjectResponse(
        id=project.id,
        organization_id=project.organization_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        repository_url=project.repository_url,
        status=project.status,
        my_role=ProjectRole.PROJECT_ADMIN,
    )


@router.get(
    "/organizations/{organization_id}/projects", response_model=list[ProjectResponse]
)
def list_projects(
    organization_id: uuid.UUID,
    user: User = Depends(get_current_user),
    org_membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> list[ProjectResponse]:
    from app.api.deps import effective_project_role

    projects = db.query(Project).filter_by(organization_id=organization_id).all()
    result: list[ProjectResponse] = []
    for project in projects:
        role = effective_project_role(db, project, user)
        if role is None:
            continue
        result.append(
            ProjectResponse(
                id=project.id,
                organization_id=project.organization_id,
                name=project.name,
                slug=project.slug,
                description=project.description,
                repository_url=project.repository_url,
                status=project.status,
                my_role=role,
            )
        )
    return result


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: uuid.UUID, ctx: ProjectContext = Depends(require_project_access)
) -> ProjectResponse:
    project = ctx.project
    return ProjectResponse(
        id=project.id,
        organization_id=project.organization_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        repository_url=project.repository_url,
        status=project.status,
        my_role=ctx.role,
    )


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> ProjectResponse:
    ctx.require_role(MANAGE_ROLES)
    project = ctx.project
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    audit.record(
        db,
        action="project.update",
        target_type="project",
        target_id=str(project.id),
        organization_id=project.organization_id,
    )
    db.commit()
    db.refresh(project)
    return ProjectResponse(
        id=project.id,
        organization_id=project.organization_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        repository_url=project.repository_url,
        status=project.status,
        my_role=ctx.role,
    )


@router.get("/projects/{project_id}/members", response_model=list[ProjectMemberResponse])
def list_project_members(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[ProjectMemberResponse]:
    members = db.query(ProjectMember).filter_by(project_id=project_id).all()
    return [
        ProjectMemberResponse(
            id=m.id, user_id=m.user.id, email=m.user.email, full_name=m.user.full_name, role=m.role
        )
        for m in members
    ]


@router.post(
    "/projects/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_project_member(
    project_id: uuid.UUID,
    payload: ProjectMemberInvite,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> ProjectMemberResponse:
    ctx.require_role(MANAGE_ROLES)
    target_user = db.query(User).filter_by(email=payload.email.lower()).first()
    if target_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No registered user found with this email")

    existing = (
        db.query(ProjectMember).filter_by(project_id=project_id, user_id=target_user.id).first()
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a project member")

    member = ProjectMember(project_id=project_id, user_id=target_user.id, role=payload.role)
    db.add(member)
    audit.record(
        db,
        action="project.member.add",
        target_type="project_member",
        target_id=str(target_user.id),
        organization_id=ctx.project.organization_id,
        extra={"project_id": str(project_id), "role": payload.role.value},
    )
    db.commit()
    db.refresh(member)
    return ProjectMemberResponse(
        id=member.id,
        user_id=target_user.id,
        email=target_user.email,
        full_name=target_user.full_name,
        role=member.role,
    )


@router.patch("/projects/{project_id}/members/{member_id}", response_model=ProjectMemberResponse)
def update_project_member_role(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: ProjectMemberRoleUpdate,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> ProjectMemberResponse:
    ctx.require_role(MANAGE_ROLES)
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    member.role = payload.role
    db.commit()
    db.refresh(member)
    return ProjectMemberResponse(
        id=member.id,
        user_id=member.user.id,
        email=member.user.email,
        full_name=member.user.full_name,
        role=member.role,
    )


@router.delete("/projects/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> None:
    ctx.require_role(MANAGE_ROLES)
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    db.delete(member)
    db.commit()


@router.get("/projects/{project_id}/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[WorkspaceResponse]:
    return db.query(Workspace).filter_by(project_id=project_id).all()


@router.post(
    "/projects/{project_id}/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace(
    project_id: uuid.UUID,
    payload: WorkspaceCreate,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> WorkspaceResponse:
    ctx.require_role({ProjectRole.PROJECT_ADMIN, ProjectRole.DEVELOPER})
    workspace = Workspace(project_id=project_id, name=payload.name, description=payload.description)
    db.add(workspace)
    audit.record(
        db,
        action="workspace.create",
        target_type="workspace",
        target_id=payload.name,
        organization_id=ctx.project.organization_id,
        extra={"project_id": str(project_id)},
    )
    db.commit()
    db.refresh(workspace)
    return workspace
