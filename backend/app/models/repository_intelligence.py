import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IndexingRunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RepositoryIntelligenceSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "repository_intelligence_settings"
    __table_args__ = (
        UniqueConstraint("project_id", "repository_connection_id", name="uq_repo_intelligence_settings"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    repository_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repository_connections.id", ondelete="CASCADE"), nullable=False
    )
    default_branch: Mapped[str] = mapped_column(String(255), default="main", nullable=False)
    included_paths: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    excluded_paths: Mapped[list] = mapped_column(
        JSON,
        default=lambda: ["node_modules", "dist", ".git", "__pycache__", "venv", ".venv", "build"],
        nullable=False,
    )
    max_file_size_kb: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    auto_index_on_sync: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RepositoryIndexingRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "repository_indexing_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    repository_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repository_connections.id", ondelete="CASCADE"), nullable=False
    )
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    status: Mapped[IndexingRunStatus] = mapped_column(
        String(50), default=IndexingRunStatus.RUNNING.value, nullable=False
    )
    graphify_version: Mapped[str] = mapped_column(String(50), default="0.9.113", nullable=False)
    entities_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relationships_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    log_output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
