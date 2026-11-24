from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class BranchInfo(BaseModel):
    name: str
    is_default: bool = False
    last_commit_sha: Optional[str] = ""
    last_commit_message: Optional[str] = ""


class RepoBranchListResponse(BaseModel):
    repository_id: str
    repository_name: str
    default_branch: str
    current_branch: str
    branches: list[BranchInfo] = Field(default_factory=list)


class OverviewMetrics(BaseModel):
    total_files: int = 0
    total_directories: int = 0
    total_classes: int = 0
    total_functions: int = 0
    lines_of_code: int = 0
    external_dependencies_count: int = 0
    languages: dict[str, int] = Field(default_factory=dict)


class IndexStatusSummary(BaseModel):
    last_indexed_at: Optional[datetime] = None
    status: str = "NOT_INDEXED"
    commit_sha: Optional[str] = ""
    duration_seconds: float = 0.0
    graphify_version: str = "0.9.113"
    entities_count: int = 0
    relationships_count: int = 0


class CommitInfo(BaseModel):
    sha: str
    message: str
    author: str = ""
    date: Optional[str] = ""


class OverviewResponse(BaseModel):
    project_id: str
    repository_id: str
    repository_name: str
    branch: str
    metrics: OverviewMetrics
    index_status: IndexStatusSummary
    recent_commits: list[CommitInfo] = Field(default_factory=list)


class CommunityPayload(BaseModel):
    id: str
    name: str
    color: str
    node_count: int
    member_node_ids: list[str] = Field(default_factory=list)


class GraphNodePayload(BaseModel):
    id: str
    label: str
    type: str
    file_path: Optional[str] = None
    location: Optional[str] = None
    community_id: Optional[str] = None
    community_name: Optional[str] = None
    community_color: Optional[str] = None
    degree: int = 0
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdgePayload(BaseModel):
    source: str
    target: str
    type: str
    provenance: str = "EXTRACTED"
    weight: float = 1.0
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphResponse(BaseModel):
    project_id: str
    repository_id: str
    branch: str
    nodes: list[GraphNodePayload] = Field(default_factory=list)
    edges: list[GraphEdgePayload] = Field(default_factory=list)
    communities: list[CommunityPayload] = Field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0
    truncated: bool = False


class NodeDetailResponse(BaseModel):
    node: GraphNodePayload
    incoming: list[GraphEdgePayload] = Field(default_factory=list)
    outgoing: list[GraphEdgePayload] = Field(default_factory=list)
    source_preview: Optional[str] = None


class NodeNeighborsResponse(BaseModel):
    center_node_id: str
    nodes: list[GraphNodePayload] = Field(default_factory=list)
    edges: list[GraphEdgePayload] = Field(default_factory=list)


class SearchResultItem(BaseModel):
    node_id: Optional[str] = None
    title: str
    file_path: str
    line_number: Optional[int] = None
    match_type: str = "file"  # file, symbol, code, intent
    snippet: str = ""
    kind: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    mode: str
    total: int = 0
    results: list[SearchResultItem] = Field(default_factory=list)


class InternalDependencyItem(BaseModel):
    source_node: str
    source_file: str
    target_node: str
    relation: str
    provenance: str = "EXTRACTED"


class ExternalDependencyItem(BaseModel):
    name: str
    version: Optional[str] = ""
    manifest_file: str = ""
    usage_count: int = 0
    dependent_files: list[str] = Field(default_factory=list)


class DependencyCycle(BaseModel):
    nodes: list[str] = Field(default_factory=list)
    length: int = 0


class DependenciesResponse(BaseModel):
    internal: list[InternalDependencyItem] = Field(default_factory=list)
    external: list[ExternalDependencyItem] = Field(default_factory=list)
    cycles: list[DependencyCycle] = Field(default_factory=list)
    total_internal: int = 0
    total_external: int = 0
    cycles_count: int = 0


class ImpactResponse(BaseModel):
    target_node: GraphNodePayload
    direct_consumers: list[GraphNodePayload] = Field(default_factory=list)
    transitive_consumers: list[GraphNodePayload] = Field(default_factory=list)
    affected_tests: list[GraphNodePayload] = Field(default_factory=list)
    affected_apis: list[GraphNodePayload] = Field(default_factory=list)
    confidence: float = 1.0
    summary: str = ""


class HistoryRunItem(BaseModel):
    id: str
    branch: str
    commit_sha: str
    status: str
    graphify_version: str
    entities_count: int
    relationships_count: int
    duration_seconds: float
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class HistoryResponse(BaseModel):
    runs: list[HistoryRunItem] = Field(default_factory=list)


class HistoryDiffResponse(BaseModel):
    run_a_id: str
    run_b_id: str
    entities_added: int = 0
    entities_removed: int = 0
    relationships_added: int = 0
    relationships_removed: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class IndexTriggerRequest(BaseModel):
    repository_id: str
    branch: Optional[str] = None
    force: Optional[bool] = False


class IndexTriggerResponse(BaseModel):
    run_id: str
    status: str
    message: str


class IndexRunDetailResponse(BaseModel):
    id: str
    status: str
    current_stage: str = "COMPLETED"
    progress_percent: int = 100
    entities_count: int = 0
    relationships_count: int = 0
    duration_seconds: float = 0.0
    log_output: str = ""
    error_message: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SettingsResponse(BaseModel):
    project_id: str
    repository_connection_id: str
    default_branch: str = "main"
    included_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    max_file_size_kb: int = 500
    auto_index_on_sync: bool = True


class SettingsUpdateRequest(BaseModel):
    repository_connection_id: str
    default_branch: Optional[str] = None
    included_paths: Optional[list[str]] = None
    excluded_paths: Optional[list[str]] = None
    max_file_size_kb: Optional[int] = None
    auto_index_on_sync: Optional[bool] = None
