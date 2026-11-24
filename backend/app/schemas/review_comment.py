from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewCommentCreate(BaseModel):
    body: str = Field(min_length=1)
    file_path: str = ""
    line_number: int | None = None


class ReviewCommentResponse(BaseModel):
    id: UUID
    project_id: UUID
    task_id: UUID
    author_user_id: UUID
    body: str
    file_path: str
    line_number: int | None
    resolved: bool
    created_at: datetime

    class Config:
        from_attributes = True
