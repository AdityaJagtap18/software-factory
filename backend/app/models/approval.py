import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ApprovalCategory(str, enum.Enum):
    CODE_CHANGE = "code_change"
    WORKFLOW_RUN = "workflow_run"
    KNOWLEDGE_UPDATE = "knowledge_update"
    PROMPT_CHANGE = "prompt_change"
    MODEL_ACTION = "model_action"
    ACCESS_SECURITY = "access_security"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ApprovalPriority(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Approval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A real governance decision record: something in the factory that
    requires explicit human authorization before (or after) it proceeds.

    This records the decision itself -- it does not perform the underlying
    action. A code-change approval tied to a task is informational/
    governance alongside the task's own real PR/merge flow (see
    `tasks.merge_task_pull_request`); approving it here does not merge
    anything, since that would create two sources of truth for the same
    real Git action.
    """

    __tablename__ = "approvals"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[ApprovalCategory] = mapped_column(
        Enum(ApprovalCategory, name="approval_category"), nullable=False
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"),
        default=ApprovalStatus.PENDING,
        nullable=False,
    )
    priority: Mapped[ApprovalPriority] = mapped_column(
        Enum(ApprovalPriority, name="approval_priority"),
        default=ApprovalPriority.MEDIUM,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str] = mapped_column(Text, default="", nullable=False)

    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )

    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    project: Mapped["Project"] = relationship()
