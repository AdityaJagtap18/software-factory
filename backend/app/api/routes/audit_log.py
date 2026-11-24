import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession

from app.api.deps import require_org_member
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.organization import OrganizationMember
from app.schemas.audit_log import AuditLogResponse

router = APIRouter(tags=["audit-log"])


@router.get(
    "/organizations/{organization_id}/audit-logs",
    response_model=list[AuditLogResponse],
)
def list_audit_logs(
    organization_id: uuid.UUID,
    action: str | None = None,
    target_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> list[AuditLogResponse]:
    """P6-2: a real read surface over the already-real `AuditLog` rows
    every route module writes via `app/services/audit.py::record` --
    the audit trail had no frontend/API consumer at all before this
    (`audit/06-SECURITY_AND_GOVERNANCE_AUDIT.md` Section 8). Any member of
    the organization can read its own audit trail; writing is never
    exposed, since every row is created only as the honest side effect of
    a real action elsewhere."""
    query = db.query(AuditLog).filter(AuditLog.organization_id == organization_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    return (
        query.order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
