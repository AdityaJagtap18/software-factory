import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ConnectionMode(str, enum.Enum):
    LOCAL_RUNTIME = "local_runtime"
    FACTORY_MANAGED = "factory_managed"
    CUSTOM_ADAPTER = "custom_adapter"


class ConnectionStatus(str, enum.Enum):
    NOT_CONFIGURED = "not_configured"
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    ERROR = "error"


class Credential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Org-scoped secret storage. The encrypted value is never returned by the API."""

    __tablename__ = "credentials"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    connections: Mapped[list["CodingAgentConnection"]] = relationship(back_populates="credential")


class CodingAgentConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An organization's configured instance of a coding-agent runtime adapter."""

    __tablename__ = "coding_agent_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "runtime_slug", name="uq_org_runtime"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    runtime_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    connection_mode: Mapped[ConnectionMode] = mapped_column(
        Enum(ConnectionMode, name="connection_mode"), nullable=False
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, name="connection_status"),
        default=ConnectionStatus.NOT_CONFIGURED,
        nullable=False,
    )
    detected_version: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    credential: Mapped["Credential | None"] = relationship(back_populates="connections")
