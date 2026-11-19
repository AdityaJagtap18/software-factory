import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.organization import OrgRole, Organization, OrganizationMember
from app.models.project import Project, ProjectMember, ProjectRole
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: DBSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def get_org_membership(
    db: DBSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMember | None:
    return (
        db.query(OrganizationMember)
        .filter_by(organization_id=organization_id, user_id=user_id)
        .first()
    )


def get_org_or_404(db: DBSession, organization_id: uuid.UUID) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return org


def require_org_member(
    organization_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> OrganizationMember:
    """FastAPI resolves `organization_id` from the path parameter of the same name."""
    get_org_or_404(db, organization_id)
    membership = get_org_membership(db, organization_id, user.id)
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organization")
    return membership


def require_org_admin(
    organization_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> OrganizationMember:
    get_org_or_404(db, organization_id)
    membership = get_org_membership(db, organization_id, user.id)
    if membership is None or membership.role != OrgRole.ORG_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Organization admin role required")
    return membership


def get_project_or_404(db: DBSession, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def get_project_membership(
    db: DBSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> ProjectMember | None:
    return db.query(ProjectMember).filter_by(project_id=project_id, user_id=user_id).first()


def effective_project_role(db: DBSession, project: Project, user: User) -> ProjectRole | None:
    """Explicit project membership wins; org admins fall back to project_admin."""
    membership = get_project_membership(db, project.id, user.id)
    if membership is not None:
        return membership.role
    org_membership = get_org_membership(db, project.organization_id, user.id)
    if org_membership is not None and org_membership.role == OrgRole.ORG_ADMIN:
        return ProjectRole.PROJECT_ADMIN
    return None


class ProjectContext:
    def __init__(self, project: Project, role: ProjectRole):
        self.project = project
        self.role = role

    def require_role(self, allowed: set[ProjectRole]) -> None:
        if self.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient project permissions")


def require_project_access(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> ProjectContext:
    project = get_project_or_404(db, project_id)
    role = effective_project_role(db, project, user)
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this project")
    return ProjectContext(project, role)
