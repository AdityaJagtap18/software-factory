import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import ProjectContext, get_current_user, require_project_access
from app.core.database import get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.document import (
    DocumentChunkResponse,
    DocumentCreate,
    DocumentResponse,
    DocumentSearchRequest,
    DocumentSearchResult,
)
from app.services import document_retrieval, embeddings

router = APIRouter(tags=["documents"])


def _to_response(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=str(document.id),
        project_id=str(document.project_id),
        title=document.title,
        source_filename=document.source_filename,
        chunk_count=len(document.chunks),
        created_at=document.created_at,
    )


def _get_document_or_404(db: DBSession, project_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


@router.get("/projects/{project_id}/documents", response_model=list[DocumentResponse])
def list_documents(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[DocumentResponse]:
    documents = db.query(Document).filter(Document.project_id == project_id).order_by(Document.created_at.desc()).all()
    return [_to_response(d) for d in documents]


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    project_id: uuid.UUID,
    payload: DocumentCreate,
    user: User = Depends(get_current_user),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> DocumentResponse:
    """Ingests real document text: chunks it and computes a real embedding
    per chunk via the local embedding model (P4-2/P4-3). 503 if that model
    isn't reachable -- never silently stores un-embedded or fake-embedded
    chunks."""
    try:
        document = document_retrieval.ingest_document(
            db,
            ctx.project,
            title=payload.title,
            content=payload.content,
            source_filename=payload.source_filename,
            created_by_user_id=user.id,
        )
    except embeddings.EmbeddingError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _to_response(document)


@router.get(
    "/projects/{project_id}/documents/{document_id}",
    response_model=list[DocumentChunkResponse],
)
def get_document_chunks(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[DocumentChunkResponse]:
    document = _get_document_or_404(db, project_id, document_id)
    return [
        DocumentChunkResponse(id=str(c.id), document_id=str(c.document_id), chunk_index=c.chunk_index, content=c.content)
        for c in sorted(document.chunks, key=lambda c: c.chunk_index)
    ]


@router.delete("/projects/{project_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> None:
    document = _get_document_or_404(db, project_id, document_id)
    db.delete(document)
    db.commit()


@router.post(
    "/projects/{project_id}/documents/search",
    response_model=list[DocumentSearchResult],
)
def search_documents(
    project_id: uuid.UUID,
    payload: DocumentSearchRequest,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> list[DocumentSearchResult]:
    """Real semantic search over this project's ingested documents (P4-4
    acceptance criterion: a document can be retrieved by a relevant query
    and cited). Returns [] if nothing is relevant or the embedding model is
    unreachable -- never fabricated matches."""
    results = document_retrieval.retrieve_relevant_chunks(db, project_id, payload.query, payload.top_k)
    return [
        DocumentSearchResult(
            chunk_id=str(r.chunk.id),
            document_id=str(r.chunk.document_id),
            document_title=r.document_title,
            chunk_index=r.chunk.chunk_index,
            content=r.chunk.content,
            score=round(1.0 - r.distance, 4),
        )
        for r in results
    ]
