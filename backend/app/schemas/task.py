from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.task import TaskPriority, TaskStatus
from app.models.task_message import TaskMessageRole


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
    git_pr_url: str = ""
    git_pr_number: int = 0
    git_pr_state: str = ""
    git_ci_status: str = ""
    git_base_branch_protected: bool = False
    git_required_status_checks: list[str] = []
    git_required_approving_reviews: int = 0

    model_config = {"from_attributes": True}


class MyTaskResponse(TaskResponse):
    project_name: str


class TaskDiffResponse(BaseModel):
    git_branch_name: str
    git_base_branch: str
    git_changed_files: list[str]
    git_diff: str

    model_config = {"from_attributes": True}


class TaskMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class TaskMessageResponse(BaseModel):
    id: UUID
    task_id: UUID
    role: TaskMessageRole
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
