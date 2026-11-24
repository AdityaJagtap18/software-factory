from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.test_run import TestFramework


class TestRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    task_id: UUID
    framework: TestFramework
    ran: bool
    passed: int
    failed: int
    total: int
    output: str
    error: str
    created_at: datetime

    class Config:
        from_attributes = True
