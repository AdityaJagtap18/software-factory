import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_current_user, require_org_admin, require_org_member
from app.core.database import get_db
from app.models.organization import OrgRole, Organization, OrganizationMember
from app.models.user import User
from app.schemas.organization import (
    MemberInvite,
    MemberRoleUpdate,
    OrganizationCreate,
    OrganizationMemberResponse,
    OrganizationResponse,
)
from app.services import audit
from app.services.slugify import slugify

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _unique_slug(db: DBSession, name: str) -> str:
    base = slugify(name)
    slug = base
    suffix = 1
    while db.query(Organization).filter_by(slug=slug).first() is not None:
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> OrganizationResponse:
    org = Organization(name=payload.name, slug=_unique_slug(db, payload.name))
    db.add(org)
    db.flush()

    membership = OrganizationMember(organization_id=org.id, user_id=user.id, role=OrgRole.ORG_ADMIN)
    db.add(membership)
    audit.record(
        db,
        action="organization.create",
        target_type="organization",
        target_id=str(org.id),
        actor_user_id=user.id,
        organization_id=org.id,
    )
    db.commit()
    db.refresh(org)
    return OrganizationResponse(id=org.id, name=org.name, slug=org.slug, my_role=OrgRole.ORG_ADMIN)


@router.get("", response_model=list[OrganizationResponse])
def list_my_organizations(
    user: User = Depends(get_current_user), db: DBSession = Depends(get_db)
) -> list[OrganizationResponse]:
    memberships = db.query(OrganizationMember).filter_by(user_id=user.id).all()
    return [
        OrganizationResponse(
            id=m.organization.id, name=m.organization.name, slug=m.organization.slug, my_role=m.role
        )
        for m in memberships
    ]


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_member),
) -> OrganizationResponse:
    org = membership.organization
    return OrganizationResponse(id=org.id, name=org.name, slug=org.slug, my_role=membership.role)


@router.get("/{organization_id}/members", response_model=list[OrganizationMemberResponse])
def list_members(
    organization_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> list[OrganizationMemberResponse]:
    members = db.query(OrganizationMember).filter_by(organization_id=organization_id).all()
    return [
        OrganizationMemberResponse(
            id=m.id, user_id=m.user.id, email=m.user.email, full_name=m.user.full_name, role=m.role
        )
        for m in members
    ]


@router.post(
    "/{organization_id}/members",
    response_model=OrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    organization_id: uuid.UUID,
    payload: MemberInvite,
    admin_membership: OrganizationMember = Depends(require_org_admin),
    db: DBSession = Depends(get_db),
) -> OrganizationMemberResponse:
    target_user = db.query(User).filter_by(email=payload.email.lower()).first()
    if target_user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No registered user found with this email"
        )
    existing = (
        db.query(OrganizationMember)
        .filter_by(organization_id=organization_id, user_id=target_user.id)
        .first()
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a member")

    member = OrganizationMember(
        organization_id=organization_id, user_id=target_user.id, role=payload.role
    )
    db.add(member)
    audit.record(
        db,
        action="organization.member.invite",
        target_type="organization_member",
        target_id=str(target_user.id),
        actor_user_id=admin_membership.user_id,
        organization_id=organization_id,
        extra={"role": payload.role.value},
    )
    db.commit()
    db.refresh(member)
    return OrganizationMemberResponse(
        id=member.id,
        user_id=target_user.id,
        email=target_user.email,
        full_name=target_user.full_name,
        role=member.role,
    )


@router.patch("/{organization_id}/members/{member_id}", response_model=OrganizationMemberResponse)
def update_member_role(
    organization_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: MemberRoleUpdate,
    admin_membership: OrganizationMember = Depends(require_org_admin),
    db: DBSession = Depends(get_db),
) -> OrganizationMemberResponse:
    member = db.get(OrganizationMember, member_id)
    if member is None or member.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")

    if member.role == OrgRole.ORG_ADMIN and payload.role != OrgRole.ORG_ADMIN:
        remaining_admins = (
            db.query(OrganizationMember)
            .filter_by(organization_id=organization_id, role=OrgRole.ORG_ADMIN)
            .count()
        )
        if remaining_admins <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Organization must retain at least one admin"
            )

    member.role = payload.role
    audit.record(
        db,
        action="organization.member.role_change",
        target_type="organization_member",
        target_id=str(member.user_id),
        actor_user_id=admin_membership.user_id,
        organization_id=organization_id,
        extra={"role": payload.role.value},
    )
    db.commit()
    db.refresh(member)
    return OrganizationMemberResponse(
        id=member.id,
        user_id=member.user.id,
        email=member.user.email,
        full_name=member.user.full_name,
        role=member.role,
    )


@router.delete("/{organization_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    organization_id: uuid.UUID,
    member_id: uuid.UUID,
    admin_membership: OrganizationMember = Depends(require_org_admin),
    db: DBSession = Depends(get_db),
) -> None:
    member = db.get(OrganizationMember, member_id)
    if member is None or member.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")

    if member.role == OrgRole.ORG_ADMIN:
        remaining_admins = (
            db.query(OrganizationMember)
            .filter_by(organization_id=organization_id, role=OrgRole.ORG_ADMIN)
            .count()
        )
        if remaining_admins <= 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Organization must retain at least one admin"
            )

    audit.record(
        db,
        action="organization.member.remove",
        target_type="organization_member",
        target_id=str(member.user_id),
        actor_user_id=admin_membership.user_id,
        organization_id=organization_id,
    )
    db.delete(member)
    db.commit()
