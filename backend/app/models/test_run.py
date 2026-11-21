import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TestFramework(str, enum.Enum):
    PYTEST = "pytest"
    NPM = "npm"
    NONE = "none"


class TestRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A real test-suite execution against a task's actual Git worktree
    (P3-1) -- `passed`/`failed`/`output` only ever come from a genuine
    subprocess run (see `app/services/test_runner.py`), never simulated."""

    __tablename__ = "test_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    framework: Mapped[TestFramework] = mapped_column(
        Enum(TestFramework, name="test_framework"), default=TestFramework.NONE, nullable=False
    )
    ran: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    project: Mapped["Project"] = relationship()
