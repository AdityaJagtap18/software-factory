import uuid

from fastapi import APIRouter, Depends, Query
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
from app.services.graph_access import GraphAccessService

router = APIRouter(tags=["knowledge"])


@router.post("/projects/{project_id}/knowledge/sync", response_model=KnowledgeSyncResponse)
def sync_project_knowledge(
    project_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> KnowledgeSyncResponse:
    """Pulls this project's real tasks, workflows, repositories, and coding-agent
    connections from Postgres and upserts them into Neo4j as real nodes
    and relationships. If Neo4j isn't reachable, this honestly reports
    `connected: false` with the real driver error -- never a fabricated
    success or a silently empty graph."""
    result = GraphAccessService.from_project_context(ctx).sync_project(db)
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
    graph_type: str = Query("project", pattern="^(project|repository|all)$"),
    ctx: ProjectContext = Depends(require_project_access),
) -> KnowledgeGraphResponse:
    graph_access = GraphAccessService.from_project_context(ctx)
    if graph_type == "repository":
        result = graph_access.get_repository_graph()
    elif graph_type == "all":
        p_res = graph_access.get_project_graph()
        r_res = graph_access.get_repository_graph()
        if not p_res.connected:
            return KnowledgeGraphResponse(connected=False, detail=p_res.detail, nodes=[], edges=[])
        seen_nodes = set()
        merged_nodes = []
        for n in p_res.nodes + r_res.nodes:
            if n.id not in seen_nodes:
                seen_nodes.add(n.id)
                merged_nodes.append(n)
        seen_edges = set()
        merged_edges = []
        for e in p_res.edges + r_res.edges:
            key = (e.source, e.target, e.type)
            if key not in seen_edges:
                seen_edges.add(key)
                merged_edges.append(e)
        return KnowledgeGraphResponse(
            connected=True,
            detail="OK",
            nodes=[
                {"id": n.id, "type": n.type, "label": str(n.label), "properties": n.properties}
                for n in merged_nodes
            ],
            edges=[{"source": e.source, "target": e.target, "type": e.type} for e in merged_edges],
        )
    else:
        result = graph_access.get_project_graph()

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
    payload: IngestRepositoryRequest = IngestRepositoryRequest(),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> IngestRepositoryResponse:
    """Parses a real directory of source files or uses the connected repository
    checkout, and upserts real File/Directory/Class/Function/Module nodes into Neo4j.
    Restricted to project admins."""
    ctx.require_role({ProjectRole.PROJECT_ADMIN})
    result = GraphAccessService.from_project_context(ctx).ingest_repository(db, payload.path or "")
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
    result = GraphAccessService.from_project_context(ctx).get_code_graph()
    return CodeGraphResponse(
        connected=result.connected,
        detail=result.detail,
        files=[
            {"path": f.path, "language": f.language, "symbols": f.symbols} for f in result.files
        ],
    )
