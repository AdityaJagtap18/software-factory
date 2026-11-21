from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.orchestration import HandoffStatus


class TaskHandoffCreate(BaseModel):
    to_connection_id: UUID
    reason: str = ""
    instruction: str | None = None


class TaskHandoffResponse(BaseModel):
    id: UUID
    task_id: UUID
    attempt_number: int
    from_connection_id: UUID | None
    to_connection_id: UUID
    reason: str
    automatic: bool
    status: HandoffStatus
    package: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskExecutionAttemptResponse(BaseModel):
    id: UUID
    task_id: UUID
    connection_id: UUID | None
    agent_slug: str
    handoff_id: UUID | None
    started_at: datetime
    completed_at: datetime | None
    succeeded: bool | None
    error_message: str

    model_config = {"from_attributes": True}


class ProviderRoutingPolicyCreate(BaseModel):
    capability: str | None = None
    fallback_chain: list[str] = Field(min_length=1)


class ProviderRoutingPolicyResponse(BaseModel):
    id: UUID
    organization_id: UUID
    capability: str | None
    fallback_chain: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
