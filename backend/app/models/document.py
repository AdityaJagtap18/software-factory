import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

# P4-3: nomic-embed-text (served locally via this project's own Ollama
# instance -- see app/services/embeddings.py) produces 768-dim vectors.
# Fixed at this dimension because pgvector columns are dimension-typed;
# changing embedding models later requires a migration + full re-embed.
EMBEDDING_DIM = 768


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A project-scoped free-text document ingested for retrieval (P4-2).

    Deliberately separate from the Neo4j Engineering/Repository Knowledge
    Graph (`knowledge_graph.py`) -- that indexes code structure as a graph;
    this indexes document prose as embedded chunks for RAG. The two are not
    merged, per `audit/05-RAG_AND_KNOWLEDGE_AUDIT.md`'s explicit warning not
    to conflate them.
    """

    __tablename__ = "documents"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    project: Mapped["Project"] = relationship()
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One real, embedded chunk of a `Document`'s text (P4-2/P4-3). Never a
    placeholder row -- `embedding` is always a real `nomic-embed-text`
    vector computed from `content` at ingestion time."""

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")
