"""Document ingestion and semantic retrieval for the RAG pipeline
(P4-2/P4-3/P4-4). Keeps embeddings in pgvector (`document_chunks.embedding`)
and performs real cosine-similarity search via pgvector's `<=>` operator --
no in-memory/approximate shortcuts, no fabricated scores.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.document import Document, DocumentChunk
from app.models.project import Project
from app.services import document_chunking, embeddings

DEFAULT_TOP_K = 5
# Cosine distance (pgvector's `<=>`) ranges 0 (identical) to 2 (opposite).
# Chunks past this distance are treated as not relevant enough to cite.
MAX_RELEVANT_DISTANCE = 0.9


def ingest_document(
    db: DBSession,
    project: Project,
    title: str,
    content: str,
    source_filename: str = "",
    created_by_user_id=None,
) -> Document:
    """Chunks `content`, computes a real embedding for every chunk, and
    stores the document + chunks. Raises `embeddings.EmbeddingError` if the
    local embedding model isn't reachable -- never stores a chunk with a
    fabricated embedding."""
    chunks_text = document_chunking.chunk_text(content)
    if not chunks_text:
        raise ValueError("Document content is empty after chunking.")

    vectors = embeddings.embed_texts(chunks_text)

    document = Document(
        project_id=project.id,
        title=title,
        source_filename=source_filename,
        content=content,
        created_by_user_id=created_by_user_id,
    )
    db.add(document)
    db.flush()

    for index, (chunk_content, vector) in enumerate(zip(chunks_text, vectors)):
        db.add(
            DocumentChunk(
                document_id=document.id,
                project_id=project.id,
                chunk_index=index,
                content=chunk_content,
                embedding=vector,
            )
        )
    db.commit()
    db.refresh(document)
    return document


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: DocumentChunk
    document_title: str
    distance: float


def retrieve_relevant_chunks(
    db: DBSession, project_id, query: str, top_k: int = DEFAULT_TOP_K
) -> list[RetrievedChunk]:
    """Real semantic search: embeds `query` and returns the `top_k` nearest
    chunks for this project by cosine distance, filtered to a relevance
    threshold. Returns `[]` (never fabricated results) if the project has no
    documents, or if the embedding model can't be reached -- a caller should
    treat that as "no retrieval context available", not an error."""
    try:
        query_vector = embeddings.embed_text(query)
    except embeddings.EmbeddingError:
        return []

    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(DocumentChunk, Document.title, distance.label("distance"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.project_id == project_id)
        .order_by(distance)
        .limit(top_k)
    )
    rows = db.execute(stmt).all()
    return [
        RetrievedChunk(chunk=chunk, document_title=title, distance=float(dist))
        for chunk, title, dist in rows
        if float(dist) <= MAX_RELEVANT_DISTANCE
    ]


def build_rag_context(db: DBSession, project_id, query: str, top_k: int = DEFAULT_TOP_K) -> str:
    """Formats retrieved chunks as a citeable grounding block for an agent
    prompt. Returns "" when nothing relevant was found, so a caller can
    unconditionally prepend this without special-casing the empty case."""
    results = retrieve_relevant_chunks(db, project_id, query, top_k)
    if not results:
        return ""
    lines = ["RELEVANT PROJECT DOCUMENTS:"]
    for r in results:
        lines.append(f"[{r.document_title}, chunk {r.chunk.chunk_index}]\n{r.chunk.content}")
    return "\n\n".join(lines)
