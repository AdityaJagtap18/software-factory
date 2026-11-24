import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TaskMessageRole(str, enum.Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class TaskMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One turn of a task's real conversation with its coding-agent runtime.

    A USER message is a real follow-up instruction submitted from the Task
    Center; an AGENT message is the real adapter output produced in
    response to it (see `app/services/task_execution.execute_followup`). A
    SYSTEM message records an honest failure (e.g. no worktree to resume)
    that never reached the adapter at all -- nothing here is fabricated.
    """

    __tablename__ = "task_messages"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[TaskMessageRole] = mapped_column(
        Enum(TaskMessageRole, name="task_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    model_id: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    runtime_slug: Mapped[str] = mapped_column(String(100), default="", nullable=False)
