import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GitProvider(str, enum.Enum):
    GITHUB = "github"


class InstallationStatus(str, enum.Enum):
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    REVOKED = "revoked"


class RepositoryConnectionStatus(str, enum.Enum):
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    ERROR = "error"


class WebhookConfigStatus(str, enum.Enum):
    NOT_CONFIGURED = "not_configured"
    REGISTERED = "registered"


class GitInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An organization's authorization to access a set of repositories
    through a Git provider -- a GitHub App installation, for the first
    supported provider. Never a long-lived personal access token: the
    installation record itself carries no credential (installation
    access tokens are minted on demand, short-lived, from this backend's
    platform-level GitHub App key in settings)."""

    __tablename__ = "git_installations"
    __table_args__ = (
        UniqueConstraint("provider", "external_installation_id", name="uq_provider_installation"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[GitProvider] = mapped_column(
        Enum(GitProvider, name="git_provider"), default=GitProvider.GITHUB, nullable=False
    )
    external_installation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    account_login: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[InstallationStatus] = mapped_column(
        Enum(InstallationStatus, name="installation_status"),
        default=InstallationStatus.NOT_CONNECTED,
        nullable=False,
    )
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    repository_connections: Mapped[list["RepositoryConnection"]] = relationship(
        back_populates="installation", passive_deletes=True
    )


class RepositoryConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One project's authorized connection to one real repository, scoped
    through a `GitInstallation` -- never resolved from a URL supplied in a
    task prompt (see Phase 9's local-path-only ingestion rationale, which
    this complements rather than reopens)."""

    __tablename__ = "repository_connections"
    __table_args__ = (
        UniqueConstraint("project_id", "full_name", name="uq_project_repository"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    git_installation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("git_installations.id", ondelete="CASCADE"), nullable=False
    )
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(511), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    selected_working_branches: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[RepositoryConnectionStatus] = mapped_column(
        Enum(RepositoryConnectionStatus, name="repository_connection_status"),
        default=RepositoryConnectionStatus.NOT_CONNECTED,
        nullable=False,
    )
    permission_scope: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_commit_sha: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    webhook_config_status: Mapped[WebhookConfigStatus] = mapped_column(
        Enum(WebhookConfigStatus, name="webhook_config_status"),
        default=WebhookConfigStatus.NOT_CONFIGURED,
        nullable=False,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    installation: Mapped["GitInstallation"] = relationship(back_populates="repository_connections")


class WebhookEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A persisted record of one inbound provider webhook delivery. The
    row's existence records receipt; `processing_result` records the real
    downstream outcome -- a webhook receipt is never, by itself, proof
    that synchronization succeeded. `provider_delivery_id` is unique so a
    redelivered event is never processed twice."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_delivery_id", name="uq_provider_delivery"),
    )

    repository_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repository_connections.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[GitProvider] = mapped_column(
        Enum(GitProvider, name="git_provider"), default=GitProvider.GITHUB, nullable=False
    )
    provider_delivery_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    repository_full_name: Mapped[str] = mapped_column(String(511), default="", nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    processing_result: Mapped[str] = mapped_column(String(255), default="", nullable=False)
