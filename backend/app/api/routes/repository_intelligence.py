import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import ProjectContext, require_project_access
from app.core.database import get_db
from app.models.project import ProjectRole
from app.models.repository_intelligence import RepositoryIndexingRun
from app.schemas.repository_intelligence import (
    DependenciesResponse,
    GraphResponse,
    HistoryDiffResponse,
    HistoryResponse,
    ImpactResponse,
    IndexRunDetailResponse,
    IndexTriggerRequest,
    IndexTriggerResponse,
    NodeDetailResponse,
    NodeNeighborsResponse,
    OverviewResponse,
    RepoBranchListResponse,
    SearchResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)
from app.services import repository_intelligence_service as ris

router = APIRouter(tags=["repository-intelligence"])


@router.get(
    "/projects/{project_id}/repository-intelligence/repositories/{repository_id}/branches",
    response_model=RepoBranchListResponse,
)
def get_repository_branches(
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> RepoBranchListResponse:
    try:
        return ris.get_repository_branches(db, project_id, repository_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/projects/{project_id}/repository-intelligence/overview",
    response_model=OverviewResponse,
)
def get_repository_overview(
    project_id: uuid.UUID,
    repository_id: uuid.UUID = Query(...),
    branch: Optional[str] = Query(None),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> OverviewResponse:
    try:
        return ris.get_overview(db, project_id, repository_id, branch)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/projects/{project_id}/repository-intelligence/graph",
    response_model=GraphResponse,
)
def get_repository_graph(
    project_id: uuid.UUID,
    repository_id: uuid.UUID = Query(...),
    branch: Optional[str] = Query(None),
    node_type: Optional[str] = Query(None),
    limit: int = Query(150, ge=1, le=1000),
    ctx: ProjectContext = Depends(require_project_access),
) -> GraphResponse:
    return ris.get_graph(project_id, repository_id, branch, node_type, limit)


@router.get(
    "/projects/{project_id}/repository-intelligence/graph/neighbors",
    response_model=NodeNeighborsResponse,
)
def get_node_neighbors_query(
    project_id: uuid.UUID,
    node_id: str = Query(...),
    repository_id: uuid.UUID = Query(...),
    branch: Optional[str] = Query(None),
    depth: int = Query(1, ge=1, le=3),
    ctx: ProjectContext = Depends(require_project_access),
) -> NodeNeighborsResponse:
    return ris.get_node_neighbors(project_id, repository_id, node_id, branch, depth)


@router.get(
    "/projects/{project_id}/repository-intelligence/graph/nodes/{node_id}/neighbors",
    response_model=NodeNeighborsResponse,
)
def get_node_neighbors(
    project_id: uuid.UUID,
    node_id: str,
    repository_id: uuid.UUID = Query(...),
    branch: Optional[str] = Query(None),
    depth: int = Query(1, ge=1, le=3),
    ctx: ProjectContext = Depends(require_project_access),
) -> NodeNeighborsResponse:
    return ris.get_node_neighbors(project_id, repository_id, node_id, branch, depth)



@router.get(
    "/projects/{project_id}/repository-intelligence/graph/nodes/{node_id:path}",
    response_model=NodeDetailResponse,
)
def get_node_details(
    project_id: uuid.UUID,
    node_id: str,
    repository_id: uuid.UUID = Query(...),
    branch: Optional[str] = Query(None),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> NodeDetailResponse:
    return ris.get_node_details(db, project_id, repository_id, node_id, branch)



@router.get(
    "/projects/{project_id}/repository-intelligence/search",
    response_model=SearchResponse,
)
def search_repository_code(
    project_id: uuid.UUID,
    repository_id: uuid.UUID = Query(...),
    q: str = Query("", alias="q"),
    mode: str = Query("all", pattern="^(all|file|symbol|code|intent)$"),
    branch: Optional[str] = Query(None),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> SearchResponse:
    return ris.search_code(db, project_id, repository_id, branch, q, mode)


@router.get(
    "/projects/{project_id}/repository-intelligence/dependencies",
    response_model=DependenciesResponse,
)
def get_repository_dependencies(
    project_id: uuid.UUID,
    repository_id: uuid.UUID = Query(...),
    branch: Optional[str] = Query(None),
    ctx: ProjectContext = Depends(require_project_access),
) -> DependenciesResponse:
    return ris.get_dependencies(project_id, repository_id, branch)


@router.get(
    "/projects/{project_id}/repository-intelligence/impact/{node_id:path}",
    response_model=ImpactResponse,
)
def get_impact_analysis(
    project_id: uuid.UUID,
    node_id: str,
    repository_id: uuid.UUID = Query(...),
    branch: Optional[str] = Query(None),
    ctx: ProjectContext = Depends(require_project_access),
) -> ImpactResponse:
    return ris.get_impact_analysis(project_id, repository_id, node_id, branch)


@router.get(
    "/projects/{project_id}/repository-intelligence/history",
    response_model=HistoryResponse,
)
def get_indexing_history(
    project_id: uuid.UUID,
    repository_id: uuid.UUID = Query(...),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> HistoryResponse:
    return ris.get_history(db, project_id, repository_id)


@router.get(
    "/projects/{project_id}/repository-intelligence/history/diff",
    response_model=HistoryDiffResponse,
)
def diff_indexing_history(
    project_id: uuid.UUID,
    run_a: uuid.UUID = Query(...),
    run_b: uuid.UUID = Query(...),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> HistoryDiffResponse:
    try:
        return ris.diff_history(db, run_a, run_b)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/projects/{project_id}/repository-intelligence/index",
    response_model=IndexTriggerResponse,
)
def trigger_repository_index(
    project_id: uuid.UUID,
    req: IndexTriggerRequest,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> IndexTriggerResponse:
    try:
        repo_uuid = uuid.UUID(req.repository_id)
        run = ris.index_repository(db, project_id, repo_uuid, req.branch, req.force or False)
        return IndexTriggerResponse(
            run_id=str(run.id),
            status=run.status,
            message="Indexing completed successfully" if run.status == "COMPLETED" else f"Indexing finished with status: {run.status}",
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get(
    "/projects/{project_id}/repository-intelligence/index/{run_id}",
    response_model=IndexRunDetailResponse,
)
def get_indexing_run_detail(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> IndexRunDetailResponse:
    run = db.get(RepositoryIndexingRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indexing run not found")

    return IndexRunDetailResponse(
        id=str(run.id),
        status=run.status,
        current_stage="COMPLETED" if run.status == "COMPLETED" else ("FAILED" if run.status == "FAILED" else "PROCESSING"),
        progress_percent=100 if run.status in ("COMPLETED", "FAILED") else 50,
        entities_count=run.entities_count,
        relationships_count=run.relationships_count,
        duration_seconds=run.duration_seconds,
        log_output=run.log_output,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


@router.get(
    "/projects/{project_id}/repository-intelligence/settings",
    response_model=SettingsResponse,
)
def get_repository_settings(
    project_id: uuid.UUID,
    repository_id: uuid.UUID = Query(...),
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> SettingsResponse:
    setting = ris.get_or_create_settings(db, project_id, repository_id)
    return SettingsResponse(
        project_id=str(setting.project_id),
        repository_connection_id=str(setting.repository_connection_id),
        default_branch=setting.default_branch,
        included_paths=setting.included_paths,
        excluded_paths=setting.excluded_paths,
        max_file_size_kb=setting.max_file_size_kb,
        auto_index_on_sync=setting.auto_index_on_sync,
    )


@router.put(
    "/projects/{project_id}/repository-intelligence/settings",
    response_model=SettingsResponse,
)
def update_repository_settings(
    project_id: uuid.UUID,
    req: SettingsUpdateRequest,
    ctx: ProjectContext = Depends(require_project_access),
    db: DBSession = Depends(get_db),
) -> SettingsResponse:
    return ris.update_settings(db, project_id, req)
