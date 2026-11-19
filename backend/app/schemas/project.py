from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.project import ProjectRole, ProjectStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    repository_url: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    repository_url: str | None = None
    status: ProjectStatus | None = None


class ProjectResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str
    repository_url: str
    status: ProjectStatus
    my_role: ProjectRole

    model_config = {"from_attributes": True}


class ProjectMemberInvite(BaseModel):
    email: EmailStr
    role: ProjectRole = ProjectRole.DEVELOPER


class ProjectMemberRoleUpdate(BaseModel):
    role: ProjectRole


class ProjectMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    full_name: str
    role: ProjectRole

    model_config = {"from_attributes": True}


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""


class WorkspaceResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: str

    model_config = {"from_attributes": True}
