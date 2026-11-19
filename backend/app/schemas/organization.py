from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.organization import OrgRole


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    my_role: OrgRole

    model_config = {"from_attributes": True}


class MemberInvite(BaseModel):
    email: EmailStr
    role: OrgRole = OrgRole.MEMBER


class MemberRoleUpdate(BaseModel):
    role: OrgRole


class OrganizationMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    full_name: str
    role: OrgRole

    model_config = {"from_attributes": True}
