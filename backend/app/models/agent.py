import enum

from sqlalchemy import JSON, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AgentStatus(str, enum.Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Phase 2 (P2-4) Agent Registry foundation: a minimal, platform-wide
    catalog entry per coding-agent runtime adapter (`app/services/
    agent_runtime/registry.py::all_adapters()`), distinct from
    `CodingAgentConnection` (an organization's configured *instance* of a
    runtime). This does not replace `CodingAgentConnection` -- it is
    additive, and exists so later orchestration/handoff work (Phase 5) has
    a real entity to assign/route to instead of a single org-scoped FK.
    Kept deliberately minimal per the roadmap: no per-version history table
    yet (`version` is a single free-form field, not a separate
    AgentVersion table) -- that is explicitly future work, not built ahead
    of need."""

    __tablename__ = "agents"

    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)
    capabilities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"), default=AgentStatus.ACTIVE, nullable=False
    )
