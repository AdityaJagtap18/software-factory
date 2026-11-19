import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Workflow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The Factory Supervisor's multi-step orchestration unit: an ordered
    sequence of Task rows (its "steps") run one after another in a
    background thread. Each step reuses the exact same execution pipeline
    as a standalone task (`app/services/task_execution.py`) — no separate,
    parallel execution path to keep honest.

    A workflow only ever reaches COMPLETED once every one of its steps has
    genuinely succeeded; the first step that really fails halts the whole
    workflow (marked FAILED) rather than continuing past it or fabricating
    success for later steps.
    """

    __tablename__ = "workflows"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, name="workflow_status"), default=WorkflowStatus.NOT_STARTED, nullable=False
    )
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_step_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship()
