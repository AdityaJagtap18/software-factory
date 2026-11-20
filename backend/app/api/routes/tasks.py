import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession
from starlette.responses import StreamingResponse

from app.api.deps import ProjectContext, get_current_user, require_project_access
from app.core.database import SessionLocal, get_db
from app.models.agent_runtime import CodingAgentConnection
from app.models.git_integration import RepositoryConnection, RepositoryConnectionStatus
from app.models.project import Project, ProjectRole
from app.models.task import Task, TaskStatus
from app.models.task_message import TaskMessage, TaskMessageRole
from app.models.user import User
from app.schemas.git_integration import MergePullRequestResult
from app.schemas.task import (
    MyTaskResponse,
    TaskCreate,
    TaskDiffResponse,
    TaskMessageCreate,
    TaskMessageResponse,
    TaskResponse,
    TaskUpdate,
)
from app.services import audit
from app.services.access import visible_project_ids
from app.services.git_provider.base import GitProviderError
from app.services.git_provider.registry import get_git_provider
from app.services.task_execution import start_followup_in_background, start_task_in_background

_STREAM_POLL_SECONDS = 0.5
_STREAM_MAX_SECONDS = 600

router = APIRouter(tags=["tasks"])

MANAGE_ROLES = {ProjectRole.PROJECT_ADMIN, ProjectRole.DEVELOPER}


def _get_task_or_404(db: DBSession, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


@router.get("/tasks/mine", response_model=list[MyTaskResponse])
def list_my_tasks(
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[MyTaskResponse]:
    """Every real task across every project this user actually belongs
    to -- the same visibility rule enforced per-project elsewhere, applied
    across all of them at once, for a genuine global "My Tasks" view."""
    project_ids = visible_project_ids(db, user)
    if not project_ids:
        return []

    projects_by_id = {p.id: p for p in db.query(Project).filter(Project.id.in_(project_ids)).all()}
    tasks = (
        db.query(Task)
        .filter(Task.project_id.in_(project_ids))
        .order_by(Task.created_at.desc())
        .all()
    )
    return [
        MyTaskResponse(
            **TaskResponse.model_validate(t).model_dump(),
            project_name=projects_by_id[t.project_id].name,
        )
        for t in tasks
    ]


@router.get("/projects/{project_id}/tasks", response_model=list[TaskResponse])
def list_tasks(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[TaskResponse]:
    return db.query(Task).filter_by(project_id=project_id).order_by(Task.created_at.desc()).all()


@router.post(
    "/projects/{project_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED
)
def create_task(
    project_id: uuid.UUID,
    payload: TaskCreate,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> TaskResponse:
    ctx.require_role(MANAGE_ROLES)

    if payload.coding_agent_connection_id is not None:
        connection = db.get(CodingAgentConnection, payload.coding_agent_connection_id)
        if connection is None or connection.organization_id != ctx.project.organization_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "coding_agent_connection_id does not belong to this project's organization",
            )

    task = Task(
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        coding_agent_connection_id=payload.coding_agent_connection_id,
        # A real, user-chosen base branch to build this task's worktree on
        # top of (see `git_worktree.prepare_worktree`) -- empty falls back
        # to the connected repository's own default branch.
        git_base_branch=payload.base_branch,
        created_by_user_id=user.id,
    )
    db.add(task)
    audit.record(
        db,
        action="task.create",
        target_type="task",
        target_id=str(task.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
        extra={"project_id": str(project_id)},
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> TaskResponse:
    return _get_task_or_404(db, project_id, task_id)


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskUpdate,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> TaskResponse:
    ctx.require_role(MANAGE_ROLES)
    task = _get_task_or_404(db, project_id, task_id)
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot edit a task while it is running")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@router.post("/projects/{project_id}/tasks/{task_id}/start", response_model=TaskResponse)
def start_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> TaskResponse:
    ctx.require_role(MANAGE_ROLES)
    task = _get_task_or_404(db, project_id, task_id)
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Task is already running")

    task.status = TaskStatus.RUNNING
    task.cancel_requested = False
    task.output = ""
    task.error_message = ""
    task.completed_at = None
    db.commit()
    db.refresh(task)

    # Runs in a background thread on its own DB session so this request
    # returns immediately with status "running" — the caller watches real
    # progress via GET .../stream (SSE) or by polling GET .../{task_id}.
    start_task_in_background(task.id)

    audit.record(
        db,
        action="task.start",
        target_type="task",
        target_id=str(task.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
    )
    db.commit()
    return task


@router.post("/projects/{project_id}/tasks/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> TaskResponse:
    ctx.require_role(MANAGE_ROLES)
    task = _get_task_or_404(db, project_id, task_id)
    if task.status != TaskStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Task is not running")

    # Signals the background thread's `should_cancel` check — it stops at
    # the next real chunk boundary (next CLI output line / SSE delta), it
    # does not fabricate an immediate stop.
    task.cancel_requested = True
    db.commit()
    audit.record(
        db,
        action="task.cancel_requested",
        target_type="task",
        target_id=str(task.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/projects/{project_id}/tasks/{task_id}/diff", response_model=TaskDiffResponse)
def get_task_diff(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> TaskDiffResponse:
    """The real diff this task's run produced inside its Git worktree
    (Phase 14) — empty fields for a task that had no repository connection
    or made no file changes, never a fabricated one."""
    return _get_task_or_404(db, project_id, task_id)


@router.post(
    "/projects/{project_id}/tasks/{task_id}/merge-pr",
    response_model=MergePullRequestResult,
)
def merge_task_pull_request(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> MergePullRequestResult:
    """Merges this task's real, already-open pull request via GitHub's own
    merge endpoint -- never a local merge, and never bypassing whatever
    protections/checks GitHub itself enforces on the base branch."""
    ctx.require_role(MANAGE_ROLES)
    task = _get_task_or_404(db, project_id, task_id)
    if not task.git_pr_number:
        raise HTTPException(status.HTTP_409_CONFLICT, "This task has no open pull request to merge")

    connection = (
        db.query(RepositoryConnection)
        .filter(
            RepositoryConnection.project_id == project_id,
            RepositoryConnection.status == RepositoryConnectionStatus.CONNECTED,
        )
        .first()
    )
    if connection is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This project has no connected repository")

    adapter = get_git_provider(connection.installation.provider.value)
    if adapter is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown git provider")
    try:
        result = adapter.merge_pull_request(
            connection.installation.external_installation_id,
            connection.owner,
            connection.name,
            task.git_pr_number,
        )
    except GitProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, exc.detail) from exc

    if result.merged:
        task.git_pr_state = "merged"
        audit.record(
            db,
            action="task.merge_pr",
            target_type="task",
            target_id=str(task.id),
            actor_user_id=user.id,
            organization_id=ctx.project.organization_id,
            extra={"pr_number": task.git_pr_number, "sha": result.sha},
        )
        db.commit()
    return MergePullRequestResult(merged=result.merged, sha=result.sha, message=result.message)


@router.get("/projects/{project_id}/tasks/{task_id}/messages", response_model=list[TaskMessageResponse])
def list_task_messages(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[TaskMessageResponse]:
    """This task's real conversation so far -- every row here was either
    typed by a real user or produced by a real adapter run; nothing is
    synthesized just to populate the Conversation tab."""
    _get_task_or_404(db, project_id, task_id)
    return (
        db.query(TaskMessage)
        .filter(TaskMessage.task_id == task_id)
        .order_by(TaskMessage.created_at.asc())
        .all()
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/messages",
    response_model=TaskMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task_message(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskMessageCreate,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> TaskMessageResponse:
    """A real follow-up instruction: stores it, then re-invokes the task's
    assigned coding-agent connection in its existing Git worktree with this
    instruction (see `execute_followup`) -- never a cosmetic echo with no
    real execution behind it."""
    ctx.require_role(MANAGE_ROLES)
    task = _get_task_or_404(db, project_id, task_id)
    if task.status == TaskStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Task is already running")

    message = TaskMessage(
        task_id=task.id, role=TaskMessageRole.USER, content=payload.content, created_by_user_id=user.id
    )
    db.add(message)
    task.status = TaskStatus.RUNNING
    db.commit()
    db.refresh(message)

    start_followup_in_background(task.id, payload.content)

    audit.record(
        db,
        action="task.followup",
        target_type="task",
        target_id=str(task.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
    )
    db.commit()
    return message


@router.get("/projects/{project_id}/tasks/{task_id}/stream")
def stream_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> StreamingResponse:
    """Server-Sent Events: real status/output updates polled from the task
    row as the background execution actually writes to it — never a
    simulated progress bar."""
    _get_task_or_404(db, project_id, task_id)

    def event_source():
        deadline = time.monotonic() + _STREAM_MAX_SECONDS
        while time.monotonic() < deadline:
            poll_db = SessionLocal()
            try:
                task = poll_db.get(Task, task_id)
                if task is None:
                    yield f"event: error\ndata: {json.dumps({'error': 'not found'})}\n\n"
                    return
                payload = {
                    "status": task.status.value,
                    "output": task.output,
                    "error_message": task.error_message,
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    "git_branch_name": task.git_branch_name,
                    "git_changed_files": task.git_changed_files,
                    "git_pr_url": task.git_pr_url,
                    "git_pr_number": task.git_pr_number,
                    "git_pr_state": task.git_pr_state,
                    "git_ci_status": task.git_ci_status,
                    "git_base_branch_protected": task.git_base_branch_protected,
                    "git_required_status_checks": task.git_required_status_checks,
                    "git_required_approving_reviews": task.git_required_approving_reviews,
                }
                yield f"data: {json.dumps(payload)}\n\n"
                if task.status != TaskStatus.RUNNING:
                    return
            finally:
                poll_db.close()
            time.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.delete("/projects/{project_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> None:
    ctx.require_role({ProjectRole.PROJECT_ADMIN})
    task = _get_task_or_404(db, project_id, task_id)
    db.delete(task)
    db.commit()
