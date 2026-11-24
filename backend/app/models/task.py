import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TaskStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A unit of work to hand to a connected coding-agent runtime.

    Execution is real, not simulated: `started_at`/`completed_at`/`output`/
    `error_message` are only ever set from an actual adapter invocation
    (see `app/services/task_execution.py`), never fabricated.
    """

    __tablename__ = "tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, name="task_priority"), default=TaskPriority.MEDIUM, nullable=False
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), default=TaskStatus.NOT_STARTED, nullable=False
    )
    coding_agent_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coding_agent_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True
    )
    step_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Phase 14: when the project has a connected repository, a task runs
    # inside its own real, isolated Git worktree/branch rather than a bare
    # prompt with no codebase. These stay empty for a task with no
    # repository connection, or if worktree preparation itself failed
    # honestly before any branch existed.
    git_branch_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    git_base_branch: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    git_diff: Mapped[str] = mapped_column(Text, default="", nullable=False)
    git_changed_files: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Phase 15: once a task with real changes finishes, its branch is
    # pushed and a real pull request opened from it. Stay empty when
    # there's no repository connection, no changes to push, or the push/PR
    # call itself failed honestly (see `task_execution.py`).
    git_pr_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    git_pr_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Phase 16: kept in sync with the real PR's lifecycle via GitHub's own
    # `pull_request` webhook ("open", "closed", or "merged") -- never
    # inferred or guessed locally; empty until Phase 15 actually opens one.
    git_pr_state: Mapped[str] = mapped_column(String(20), default="", nullable=False)

    # Phase 17: the real CI result for this task's branch, kept in sync by
    # GitHub's own `check_suite` webhook ("queued", "in_progress", or a
    # real conclusion like "success"/"failure") -- never run or simulated
    # by this backend itself, and empty until GitHub reports one.
    git_ci_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)

    # Phase 18: the base branch's real branch protection rules, as GitHub
    # itself reports them at the moment the pull request is opened --
    # informational only (this backend never enforces or bypasses them;
    # GitHub's own merge button does that). Stays empty/false when there's
    # no PR, or the lookup itself failed (see `task_execution.py`).
    git_base_branch_protected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    git_required_status_checks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    git_required_approving_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Automatically retrieved project and repository graph context
    knowledge_context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # ChatGPT-Style Model & Runtime Selection
    selected_model: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    execution_runtime: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    execution_history: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    project: Mapped["Project"] = relationship()
