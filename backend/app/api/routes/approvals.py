import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import ProjectContext, get_current_user, require_project_access
from app.core.database import get_db
from app.models.approval import Approval, ApprovalStatus
from app.models.project import ProjectRole
from app.models.user import User
from app.schemas.approval import ApprovalCreate, ApprovalDecision, ApprovalResponse
from app.services import audit

router = APIRouter(tags=["approvals"])

DECIDE_ROLES = {ProjectRole.PROJECT_ADMIN, ProjectRole.DEVELOPER}


def _get_approval_or_404(db: DBSession, project_id: uuid.UUID, approval_id: uuid.UUID) -> Approval:
    approval = db.get(Approval, approval_id)
    if approval is None or approval.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found")
    return approval


@router.get("/projects/{project_id}/approvals", response_model=list[ApprovalResponse])
def list_approvals(
    project_id: uuid.UUID,
    status_filter: ApprovalStatus | None = Query(None, alias="status"),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[Approval]:
    query = db.query(Approval).filter(Approval.project_id == project_id)
    if status_filter is not None:
        query = query.filter(Approval.status == status_filter)
    return query.order_by(Approval.created_at.desc()).all()


@router.post("/projects/{project_id}/approvals", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
def create_approval(
    project_id: uuid.UUID,
    payload: ApprovalCreate,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> Approval:
    approval = Approval(
        project_id=project_id,
        category=payload.category,
        title=payload.title,
        subtitle=payload.subtitle,
        priority=payload.priority,
        task_id=payload.task_id,
        requested_by_user_id=user.id,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


@router.post("/projects/{project_id}/approvals/{approval_id}/decide", response_model=ApprovalResponse)
def decide_approval(
    project_id: uuid.UUID,
    approval_id: uuid.UUID,
    payload: ApprovalDecision,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> Approval:
    """Records a real governance decision on this approval request. This
    does not itself perform the underlying action (e.g. merging a task's
    pull request) -- that stays a separate, explicit real action so there
    is never more than one source of truth for it."""
    ctx.require_role(DECIDE_ROLES)
    approval = _get_approval_or_404(db, project_id, approval_id)
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "This approval has already been decided")
    if payload.decision == ApprovalStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be approved, rejected, or changes_requested")

    approval.status = payload.decision
    approval.decision_note = payload.note
    approval.decided_by_user_id = user.id
    approval.decided_at = datetime.now(timezone.utc)
    audit.record(
        db,
        action="approval.decide",
        target_type="approval",
        target_id=str(approval.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
        extra={"decision": payload.decision.value, "category": approval.category.value},
    )
    db.commit()
    db.refresh(approval)
    return approval
