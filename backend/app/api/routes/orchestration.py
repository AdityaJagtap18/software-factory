import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import ProjectContext, get_current_user, require_org_admin, require_org_member, require_project_access
from app.core.database import get_db
from app.models.agent_runtime import CodingAgentConnection
from app.models.organization import OrganizationMember
from app.models.orchestration import ProviderRoutingPolicy, TaskExecutionAttempt, TaskHandoff
from app.models.project import ProjectRole
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.orchestration import (
    ProviderRoutingPolicyCreate,
    ProviderRoutingPolicyResponse,
    TaskExecutionAttemptResponse,
    TaskHandoffCreate,
    TaskHandoffResponse,
)
from app.services import audit, handoff as handoff_service

router = APIRouter(tags=["orchestration"])

MANAGE_ROLES = {ProjectRole.PROJECT_ADMIN, ProjectRole.DEVELOPER}


def _get_task_or_404(db: DBSession, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


@router.post(
    "/projects/{project_id}/tasks/{task_id}/handoff",
    response_model=TaskHandoffResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task_handoff(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskHandoffCreate,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> TaskHandoffResponse:
    """P5-2: a human-triggered agent replacement -- a real, versioned
    handover package is built from this task's actual state (worktree,
    output, test results, review comments) and the named connection
    resumes the SAME worktree/branch with it, never a stateless restart."""
    ctx.require_role(MANAGE_ROLES)
    task = _get_task_or_404(db, project_id, task_id)
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Task is already running")

    to_connection = db.get(CodingAgentConnection, payload.to_connection_id)
    if to_connection is None or to_connection.organization_id != ctx.project.organization_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "to_connection_id does not belong to this project's organization",
        )

    handoff = handoff_service.create_handoff(
        db, task, payload.to_connection_id, payload.reason, triggered_by_user_id=user.id
    )
    task.status = TaskStatus.RUNNING
    db.commit()

    handoff_service.start_handoff_in_background(task.id, handoff.id, payload.instruction)

    audit.record(
        db,
        action="task.handoff",
        target_type="task",
        target_id=str(task.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
        extra={"to_connection_id": str(payload.to_connection_id), "reason": payload.reason},
    )
    db.commit()
    return handoff


@router.get(
    "/projects/{project_id}/tasks/{task_id}/handoffs",
    response_model=list[TaskHandoffResponse],
)
def list_task_handoffs(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[TaskHandoffResponse]:
    _get_task_or_404(db, project_id, task_id)
    return (
        db.query(TaskHandoff)
        .filter(TaskHandoff.task_id == task_id)
        .order_by(TaskHandoff.attempt_number.asc())
        .all()
    )


@router.get(
    "/projects/{project_id}/tasks/{task_id}/attempts",
    response_model=list[TaskExecutionAttemptResponse],
)
def list_task_execution_attempts(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[TaskExecutionAttemptResponse]:
    """P5-1/P5-2: the immutable, ordered record of every real adapter
    invocation this task has ever had -- which agent ran it, whether it
    was a resumed handoff, and whether it genuinely succeeded."""
    _get_task_or_404(db, project_id, task_id)
    return (
        db.query(TaskExecutionAttempt)
        .filter(TaskExecutionAttempt.task_id == task_id)
        .order_by(TaskExecutionAttempt.started_at.asc())
        .all()
    )


@router.post(
    "/organizations/{organization_id}/routing-policies",
    response_model=ProviderRoutingPolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_routing_policy(
    organization_id: uuid.UUID,
    payload: ProviderRoutingPolicyCreate,
    user: User = Depends(get_current_user),
    admin_membership: OrganizationMember = Depends(require_org_admin),
    db: DBSession = Depends(get_db),
) -> ProviderRoutingPolicyResponse:
    """P5-3: an org admin's policy-controlled fallback chain -- the order
    in which `app/services/agent_assignment.py::select_connection` tries
    runtime slugs for a capability (or organization-wide, if `capability`
    is omitted). Replaces any existing policy for the same
    (organization, capability) pair rather than creating a duplicate."""
    existing = (
        db.query(ProviderRoutingPolicy)
        .filter(
            ProviderRoutingPolicy.organization_id == organization_id,
            ProviderRoutingPolicy.capability == payload.capability,
        )
        .first()
    )
    if existing is not None:
        existing.fallback_chain = payload.fallback_chain
        existing.created_by_user_id = user.id
        db.commit()
        db.refresh(existing)
        return existing

    policy = ProviderRoutingPolicy(
        organization_id=organization_id,
        capability=payload.capability,
        fallback_chain=payload.fallback_chain,
        created_by_user_id=user.id,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


@router.get(
    "/organizations/{organization_id}/routing-policies",
    response_model=list[ProviderRoutingPolicyResponse],
)
def list_routing_policies(
    organization_id: uuid.UUID,
    membership: OrganizationMember = Depends(require_org_member),
    db: DBSession = Depends(get_db),
) -> list[ProviderRoutingPolicyResponse]:
    return (
        db.query(ProviderRoutingPolicy)
        .filter(ProviderRoutingPolicy.organization_id == organization_id)
        .order_by(ProviderRoutingPolicy.created_at.desc())
        .all()
    )


@router.delete(
    "/organizations/{organization_id}/routing-policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_routing_policy(
    organization_id: uuid.UUID,
    policy_id: uuid.UUID,
    admin_membership: OrganizationMember = Depends(require_org_admin),
    db: DBSession = Depends(get_db),
) -> None:
    policy = db.get(ProviderRoutingPolicy, policy_id)
    if policy is None or policy.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Routing policy not found")
    db.delete(policy)
    db.commit()
