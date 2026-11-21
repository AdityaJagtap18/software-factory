from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.task import TaskPriority, TaskStatus
from app.models.task_message import TaskMessageRole


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    coding_agent_connection_id: UUID | None = None
    base_branch: str = ""


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
    required_capability: str = ""
    depends_on_step_orders: list[int] = []
    max_retries: int = 0
    retry_count: int = 0

    @field_validator("depends_on_step_orders", mode="before")
    @classmethod
    def _none_means_no_explicit_deps(cls, value: list[int] | None) -> list[int]:
        """The ORM column is nullable -- `None` means "no explicit
        dependency declared" (implicit sequential default), distinct from
        `[]` (explicit "depends on nothing"). The API response always
        reports a concrete list; callers that care about the distinction
        use the workflow-create request shape, not this response."""
        return value if value is not None else []
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
    safety_flags: list[dict] = []

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
