from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.approval import ApprovalCategory, ApprovalPriority, ApprovalStatus


class ApprovalCreate(BaseModel):
    category: ApprovalCategory
    title: str = Field(min_length=1, max_length=255)
    subtitle: str = ""
    priority: ApprovalPriority = ApprovalPriority.MEDIUM
    task_id: UUID | None = None


class ApprovalDecision(BaseModel):
    decision: ApprovalStatus
    note: str = ""


class ApprovalResponse(BaseModel):
    id: UUID
    project_id: UUID
    category: ApprovalCategory
    status: ApprovalStatus
    priority: ApprovalPriority
    title: str
    subtitle: str
    task_id: UUID | None
    requested_by_user_id: UUID | None
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_note: str
    created_at: datetime

    class Config:
        from_attributes = True
