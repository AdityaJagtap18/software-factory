import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import ProjectContext, get_current_user, require_project_access
from app.core.database import get_db
from app.models.agent_runtime import CodingAgentConnection
from app.models.project import ProjectRole
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.task import TaskCreate, TaskResponse, TaskUpdate
from app.services import audit
from app.services.task_execution import run_task

router = APIRouter(tags=["tasks"])

MANAGE_ROLES = {ProjectRole.PROJECT_ADMIN, ProjectRole.DEVELOPER}


def _get_task_or_404(db: DBSession, project_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


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
    db.commit()

    run_task(db, task)

    audit.record(
        db,
        action="task.start",
        target_type="task",
        target_id=str(task.id),
        actor_user_id=user.id,
        organization_id=ctx.project.organization_id,
        extra={"status": task.status.value},
    )
    db.commit()
    db.refresh(task)
    return task


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
