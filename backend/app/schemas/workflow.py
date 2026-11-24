from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.workflow import WorkflowStatus
from app.schemas.task import TaskResponse


class WorkflowStepCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    coding_agent_connection_id: UUID | None = None
    required_capability: str = ""
    depends_on_step_orders: list[int] | None = None
    max_retries: int = Field(default=0, ge=0, le=5)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    steps: list[WorkflowStepCreate] = Field(min_length=1)


class WorkflowResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: str
    status: WorkflowStatus
    current_step_index: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    steps: list[TaskResponse]
    shared_context: dict = {}

    model_config = {"from_attributes": True}


class MyWorkflowResponse(WorkflowResponse):
    project_name: str
