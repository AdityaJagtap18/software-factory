import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession
from starlette.responses import StreamingResponse

from app.api.deps import ProjectContext, get_current_user, require_project_access
from app.core.database import SessionLocal, get_db
from app.models.agent_runtime import CodingAgentConnection
from app.models.project import Project, ProjectRole
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.models.workflow import Workflow, WorkflowStatus
from app.schemas.workflow import MyWorkflowResponse, WorkflowCreate, WorkflowResponse
from app.services import audit
from app.services.access import visible_project_ids
from app.services.workflow_execution import start_workflow_in_background

_STREAM_POLL_SECONDS = 0.5
_STREAM_MAX_SECONDS = 600

router = APIRouter(tags=["workflows"])

MANAGE_ROLES = {ProjectRole.PROJECT_ADMIN, ProjectRole.DEVELOPER}


def _get_workflow_or_404(db: DBSession, project_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or workflow.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    return workflow


def _steps(db: DBSession, workflow_id: uuid.UUID) -> list[Task]:
    return db.query(Task).filter_by(workflow_id=workflow_id).order_by(Task.step_order).all()


def _to_response(db: DBSession, workflow: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        project_id=workflow.project_id,
        name=workflow.name,
        description=workflow.description,
        status=workflow.status,
        current_step_index=workflow.current_step_index,
        started_at=workflow.started_at,
        completed_at=workflow.completed_at,
        created_at=workflow.created_at,
        steps=_steps(db, workflow.id),
    )


@router.get("/workflows/mine", response_model=list[MyWorkflowResponse])
def list_my_workflows(
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[MyWorkflowResponse]:
    """Every real workflow across every project this user actually
    belongs to, each with its real project name and real step list --
    the same visibility rule enforced per-project elsewhere, applied
    across all of them at once."""
    project_ids = visible_project_ids(db, user)
    if not project_ids:
        return []

    projects_by_id = {p.id: p for p in db.query(Project).filter(Project.id.in_(project_ids)).all()}
    workflows = (
        db.query(Workflow)
        .filter(Workflow.project_id.in_(project_ids))
        .order_by(Workflow.created_at.desc())
        .all()
    )
    return [
        MyWorkflowResponse(
            **_to_response(db, wf).model_dump(),
            project_name=projects_by_id[wf.project_id].name,
        )
        for wf in workflows
    ]


@router.get("/projects/{project_id}/workflows", response_model=list[WorkflowResponse])
def list_workflows(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[WorkflowResponse]:
    workflows = (
        db.query(Workflow).filter_by(project_id=project_id).order_by(Workflow.created_at.desc()).all()
    )
    return [_to_response(db, wf) for wf in workflows]


@router.post(
    "/projects/{project_id}/workflows",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow(
    project_id: uuid.UUID,
    payload: WorkflowCreate,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> WorkflowResponse:
    ctx.require_role(MANAGE_ROLES)

    for step in payload.steps:
        if step.coding_agent_connection_id is not None:
            connection = db.get(CodingAgentConnection, step.coding_agent_connection_id)
            if connection is None or connection.organization_id != ctx.project.organization_id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "coding_agent_connection_id does not belong to this project's organization",
                )

    workflow = Workflow(
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        created_by_user_id=user.id,
    )
    db.add(workflow)
    db.flush()

    for order, step in enumerate(payload.steps):
        db.add(
            Task(
                project_id=project_id,
                title=step.title,
                description=step.description,
                coding_agent_connection_id=step.coding_agent_connection_id,
                created_by_user_id=user.id,
                workflow_id=workflow.id,
                step_order=order,
            )
        )

    audit.record(
        db,
        action="workflow.create",
        target_type="workflow",
        target_id=str(workflow.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
        extra={"project_id": str(project_id), "step_count": len(payload.steps)},
    )
    db.commit()
    db.refresh(workflow)
    return _to_response(db, workflow)


@router.get("/projects/{project_id}/workflows/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    project_id: uuid.UUID,
    workflow_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> WorkflowResponse:
    workflow = _get_workflow_or_404(db, project_id, workflow_id)
    return _to_response(db, workflow)


@router.post("/projects/{project_id}/workflows/{workflow_id}/start", response_model=WorkflowResponse)
def start_workflow(
    project_id: uuid.UUID,
    workflow_id: uuid.UUID,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> WorkflowResponse:
    ctx.require_role(MANAGE_ROLES)
    workflow = _get_workflow_or_404(db, project_id, workflow_id)
    if workflow.status == WorkflowStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow is already running")

    workflow.status = WorkflowStatus.RUNNING
    workflow.cancel_requested = False
    workflow.current_step_index = 0
    workflow.completed_at = None
    db.commit()
    db.refresh(workflow)

    # Runs the Factory Supervisor's step sequencer in a background thread
    # on its own DB session so this request returns immediately with
    # status "running" — watch real progress via GET .../stream or by
    # polling GET .../{workflow_id}.
    start_workflow_in_background(workflow.id)

    audit.record(
        db,
        action="workflow.start",
        target_type="workflow",
        target_id=str(workflow.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
    )
    db.commit()
    return _to_response(db, workflow)


@router.post("/projects/{project_id}/workflows/{workflow_id}/cancel", response_model=WorkflowResponse)
def cancel_workflow(
    project_id: uuid.UUID,
    workflow_id: uuid.UUID,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> WorkflowResponse:
    ctx.require_role(MANAGE_ROLES)
    workflow = _get_workflow_or_404(db, project_id, workflow_id)
    if workflow.status != WorkflowStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow is not running")

    # Checked before the next step starts, and threaded into the currently
    # running step's `should_cancel` so it stops at the next real chunk
    # boundary — never a fabricated instant stop.
    workflow.cancel_requested = True
    db.commit()
    audit.record(
        db,
        action="workflow.cancel_requested",
        target_type="workflow",
        target_id=str(workflow.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
    )
    db.commit()
    db.refresh(workflow)
    return _to_response(db, workflow)


@router.get("/projects/{project_id}/workflows/{workflow_id}/stream")
def stream_workflow(
    project_id: uuid.UUID,
    workflow_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> StreamingResponse:
    """Server-Sent Events: real workflow + current-step status polled from
    the database as the background supervisor actually writes to it."""
    _get_workflow_or_404(db, project_id, workflow_id)

    def event_source():
        deadline = time.monotonic() + _STREAM_MAX_SECONDS
        while time.monotonic() < deadline:
            poll_db = SessionLocal()
            try:
                workflow = poll_db.get(Workflow, workflow_id)
                if workflow is None:
                    yield f"event: error\ndata: {json.dumps({'error': 'not found'})}\n\n"
                    return
                steps = _steps(poll_db, workflow_id)
                payload = {
                    "status": workflow.status.value,
                    "current_step_index": workflow.current_step_index,
                    "step_count": len(steps),
                    "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
                    "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None,
                    "steps": [
                        {
                            "id": str(s.id),
                            "title": s.title,
                            "status": s.status.value,
                            "output": s.output,
                            "error_message": s.error_message,
                        }
                        for s in steps
                    ],
                }
                yield f"data: {json.dumps(payload)}\n\n"
                if workflow.status != WorkflowStatus.RUNNING:
                    return
            finally:
                poll_db.close()
            time.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.delete("/projects/{project_id}/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    project_id: uuid.UUID,
    workflow_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> None:
    ctx.require_role({ProjectRole.PROJECT_ADMIN})
    workflow = _get_workflow_or_404(db, project_id, workflow_id)
    db.delete(workflow)
    db.commit()
