"""Phase 5 (B1/B2/B3) orchestration entities: additive to the existing
`Task`/`Workflow`/`Agent`/`CodingAgentConnection` models, never a parallel
execution path that duplicates them.

`TaskExecutionAttempt` is the immutable per-attempt log: exactly one row is
appended for every real adapter invocation (a task's first run, a
follow-up turn, or a resumed handoff) -- it is never updated to pretend an
attempt didn't happen or edited after the fact, matching the roadmap's
"immutable execution attempt history" / "record which agent performed each
action" requirements.

`TaskHandoff` is the versioned handover package (B2): one row per handoff,
never overwritten -- a second handoff on the same task is a new row with a
higher `attempt_number`, so the full fallback/replacement history is
reconstructable. `package` is a JSON snapshot built honestly from real rows
at the moment of handoff (see `app/services/handoff.py::build_handover_package`)
-- it is not a live reference that could drift after the fact.

`ProviderRoutingPolicy` is the policy-controlled fallback chain (B3): an
ordered list of runtime slugs to try for a given capability (or
organization-wide if `capability` is null), used both by automatic
capability-based assignment (B1) and by the "next provider to try" step of
an automatic handoff-on-failure (B2/B3 overlap, deliberately -- the
roadmap treats them as one fallback mechanism, not two)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TaskExecutionAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One real adapter invocation against a task. `handoff_id` is set only
    when this attempt was the resumption of a `TaskHandoff` (i.e. a
    different connection/agent took over) -- null for a task's first run
    or an ordinary same-agent follow-up turn."""

    __tablename__ = "task_execution_attempts"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coding_agent_connections.id", ondelete="SET NULL"), nullable=True
    )
    agent_slug: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    handoff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_handoffs.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    succeeded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # null while still running
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # P6-3: real provider usage fields, when the adapter's execution result
    # actually returned any (see `ExecutionResult.usage` in
    # `app/services/agent_runtime/base.py`) -- empty `{}` for every adapter
    # that genuinely has nothing to report (every local-CLI adapter today),
    # never a fabricated estimate.
    usage: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class TaskExecutionSpan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """P6-3: a structured trace span over one real, already-happening phase
    of an attempt's execution (worktree preparation, the adapter
    invocation itself, diff collection, PR push/open, the test run) --
    timestamps taken around work this backend already does, never a
    synthetic/estimated duration. `attempt_id` ties every span back to the
    single `TaskExecutionAttempt` it belongs to, so a task's full
    execution trace is reconstructable as the ordered attempts, each with
    its ordered spans."""

    __tablename__ = "task_execution_spans"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_execution_attempts.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    succeeded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)


class HandoffStatus(str, enum.Enum):
    PENDING = "pending"  # created, not yet resumed
    RESUMED = "resumed"  # a new attempt picked it up and ran to completion (success or failure)
    SUPERSEDED = "superseded"  # a later handoff on the same task replaced this one before it was resumed


class TaskHandoff(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A versioned handover package (B2). `attempt_number` increments per
    task starting at 1, so the ordered history of handoffs on one task is
    reconstructable by `(task_id, attempt_number)` without relying on
    `created_at` ordering alone."""

    __tablename__ = "task_handoffs"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coding_agent_connections.id", ondelete="SET NULL"), nullable=True
    )
    to_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coding_agent_connections.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    automatic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[HandoffStatus] = mapped_column(
        Enum(HandoffStatus, name="handoff_status"), default=HandoffStatus.PENDING, nullable=False
    )
    package: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ProviderRoutingPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """B3: an organization's ordered fallback chain of runtime slugs for a
    given capability. `capability` null means "the organization-wide
    default chain" (used when no capability-specific policy matches)."""

    __tablename__ = "provider_routing_policies"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    capability: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fallback_chain: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
