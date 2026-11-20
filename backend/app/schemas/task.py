from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.task import TaskPriority, TaskStatus


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    coding_agent_connection_id: UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: TaskPriority | None = None
    coding_agent_connection_id: UUID | None = None


class TaskResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str
    priority: TaskPriority
    status: TaskStatus
    coding_agent_connection_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    output: str
    error_message: str
    created_at: datetime
    workflow_id: UUID | None = None
    step_order: int | None = None
    git_branch_name: str = ""
    git_base_branch: str = ""
    git_changed_files: list[str] = []

    model_config = {"from_attributes": True}


class MyTaskResponse(TaskResponse):
    project_name: str


class TaskDiffResponse(BaseModel):
    git_branch_name: str
    git_base_branch: str
    git_changed_files: list[str]
    git_diff: str

    model_config = {"from_attributes": True}
