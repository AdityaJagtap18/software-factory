import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.api.deps import ProjectContext, require_project_access
from app.core.database import get_db
from app.models.project import ProjectRole
from app.schemas.knowledge import (
    CodeGraphResponse,
    IngestRepositoryRequest,
    IngestRepositoryResponse,
    KnowledgeGraphResponse,
    KnowledgeSyncResponse,
)
from app.services import knowledge_graph

router = APIRouter(tags=["knowledge"])


@router.post("/projects/{project_id}/knowledge/sync", response_model=KnowledgeSyncResponse)
def sync_project_knowledge(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> KnowledgeSyncResponse:
    """Pulls this project's real tasks, workflows, and coding-agent
    connections from Postgres and upserts them into Neo4j as real nodes
    and relationships. If Neo4j isn't reachable, this honestly reports
    `connected: false` with the real driver error -- never a fabricated
    success or a silently empty graph."""
    result = knowledge_graph.sync_project(db, ctx.project)
    return KnowledgeSyncResponse(
        connected=result.connected,
        detail=result.detail,
        nodes_synced=result.nodes_synced,
        relationships_synced=result.relationships_synced,
        synced_at=result.synced_at,
    )


@router.get("/projects/{project_id}/knowledge/graph", response_model=KnowledgeGraphResponse)
def get_project_knowledge_graph(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
) -> KnowledgeGraphResponse:
    result = knowledge_graph.get_project_graph(project_id)
    return KnowledgeGraphResponse(
        connected=result.connected,
        detail=result.detail,
        nodes=[
            {"id": n.id, "type": n.type, "label": str(n.label), "properties": n.properties}
            for n in result.nodes
        ],
        edges=[{"source": e.source, "target": e.target, "type": e.type} for e in result.edges],
    )


@router.post(
    "/projects/{project_id}/knowledge/ingest-repository", response_model=IngestRepositoryResponse
)
def ingest_repository(
    project_id: uuid.UUID,
    payload: IngestRepositoryRequest,
    ctx: ProjectContext = Depends(require_project_access),
) -> IngestRepositoryResponse:
    """Parses a real directory of source files already present on the
    backend host and upserts real File/Function/Class nodes into Neo4j.
    Restricted to project admins: this reads whatever filesystem path the
    backend process can see, so it's an elevated operation, not a
    read-only one. There is deliberately no remote-git-URL variant of
    this endpoint -- that would let any caller make the backend fetch
    arbitrary network locations."""
    ctx.require_role({ProjectRole.PROJECT_ADMIN})
    result = knowledge_graph.ingest_repository(ctx.project, payload.path)
    return IngestRepositoryResponse(
        connected=result.connected,
        detail=result.detail,
        files_scanned=result.files_scanned,
        symbols_found=result.symbols_found,
        nodes_synced=result.nodes_synced,
        relationships_synced=result.relationships_synced,
        synced_at=result.synced_at,
    )


@router.get("/projects/{project_id}/knowledge/code-graph", response_model=CodeGraphResponse)
def get_project_code_graph(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
) -> CodeGraphResponse:
    result = knowledge_graph.get_code_graph(project_id)
    return CodeGraphResponse(
        connected=result.connected,
        detail=result.detail,
        files=[
            {"path": f.path, "language": f.language, "symbols": f.symbols} for f in result.files
        ],
    )
