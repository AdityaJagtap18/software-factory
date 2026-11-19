"""Computes a user's whole visible-project set at once -- the same
access rule `require_project_access` enforces per-request (explicit
project membership, or org-admin of the project's organization) -- for
endpoints (dashboard summary, cross-project task lists) that need it in
bulk rather than one project at a time.
"""

import uuid

from sqlalchemy.orm import Session as DBSession

from app.models.organization import OrgRole, OrganizationMember
from app.models.project import Project, ProjectMember
from app.models.user import User


def visible_project_ids(db: DBSession, user: User) -> set[uuid.UUID]:
    org_ids = [
        m.organization_id for m in db.query(OrganizationMember).filter_by(user_id=user.id).all()
    ]
    if not org_ids:
        return set()

    admin_org_ids = {
        m.organization_id
        for m in db.query(OrganizationMember).filter_by(user_id=user.id).all()
        if m.role == OrgRole.ORG_ADMIN
    }
    member_project_ids = {
        m.project_id for m in db.query(ProjectMember).filter_by(user_id=user.id).all()
    }

    projects = db.query(Project).filter(Project.organization_id.in_(org_ids)).all()
    return {
        p.id
        for p in projects
        if p.id in member_project_ids or p.organization_id in admin_org_ids
    }
