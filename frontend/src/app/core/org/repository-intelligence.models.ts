export interface BranchInfo {
  name: string;
  is_default: boolean;
  last_commit_sha?: string;
  last_commit_message?: string;
}

export interface RepoBranchListResponse {
  repository_id: string;
  repository_name: string;
  default_branch: string;
  current_branch: string;
  branches: BranchInfo[];
}

export interface OverviewMetrics {
  total_files: number;
  total_directories: number;
  total_classes: number;
  total_functions: number;
  lines_of_code: number;
  external_dependencies_count: number;
  languages: Record<string, number>;
}

export interface IndexStatusSummary {
  last_indexed_at?: string | null;
  status: string;
  commit_sha?: string;
  duration_seconds: number;
  graphify_version: string;
  entities_count: number;
  relationships_count: number;
}

export interface CommitInfo {
  sha: string;
  message: string;
  author: string;
  date?: string;
}

export interface OverviewResponse {
  project_id: string;
  repository_id: string;
  repository_name: string;
  branch: string;
  metrics: OverviewMetrics;
  index_status: IndexStatusSummary;
  recent_commits: CommitInfo[];
}

export interface CommunityPayload {
  id: string;
  name: string;
  color: string;
  node_count: number;
  member_node_ids: string[];
  visible?: boolean;
}

export interface GraphNodePayload {
  id: string;
  label: string;
  type: string;
  file_path?: string | null;
  location?: string | null;
  community_id?: string | null;
  community_name?: string | null;
  community_color?: string | null;
  degree?: number;
  properties?: Record<string, any>;
  // For canvas layout coordinates and physics
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
  radius?: number;
}

export interface GraphEdgePayload {
  source: string;
  target: string;
  type: string;
  provenance: string;
  weight: number;
  properties?: Record<string, any>;
}

export interface GraphResponse {
  project_id: string;
  repository_id: string;
  branch: string;
  nodes: GraphNodePayload[];
  edges: GraphEdgePayload[];
  communities: CommunityPayload[];
  total_nodes: number;
  total_edges: number;
  truncated: boolean;
}

export interface NodeDetailResponse {
  node: GraphNodePayload;
  incoming: GraphEdgePayload[];
  outgoing: GraphEdgePayload[];
  source_preview?: string | null;
}

export interface NodeNeighborsResponse {
  center_node_id: string;
  nodes: GraphNodePayload[];
  edges: GraphEdgePayload[];
}

export interface SearchResultItem {
  node_id?: string | null;
  title: string;
  file_path: string;
  line_number?: number | null;
  match_type: 'file' | 'symbol' | 'code' | 'intent';
  snippet: string;
  kind?: string | null;
}

export interface SearchResponse {
  query: string;
  mode: string;
  total: number;
  results: SearchResultItem[];
}

export interface InternalDependencyItem {
  source_node: string;
  source_file: string;
  target_node: string;
  relation: string;
  provenance: string;
}

export interface ExternalDependencyItem {
  name: string;
  version?: string;
  manifest_file: string;
  usage_count: number;
  dependent_files: string[];
}

export interface DependencyCycle {
  nodes: string[];
  length: number;
}

export interface DependenciesResponse {
  internal: InternalDependencyItem[];
  external: ExternalDependencyItem[];
  cycles: DependencyCycle[];
  total_internal: number;
  total_external: number;
  cycles_count: number;
}

export interface ImpactResponse {
  target_node: GraphNodePayload;
  direct_consumers: GraphNodePayload[];
  transitive_consumers: GraphNodePayload[];
  affected_tests: GraphNodePayload[];
  affected_apis: GraphNodePayload[];
  confidence: number;
  summary: string;
}

export interface HistoryRunItem {
  id: string;
  branch: string;
  commit_sha: string;
  status: string;
  graphify_version: string;
  entities_count: number;
  relationships_count: number;
  duration_seconds: number;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface HistoryResponse {
  runs: HistoryRunItem[];
}

export interface HistoryDiffResponse {
  run_a_id: string;
  run_b_id: string;
  entities_added: number;
  entities_removed: number;
  relationships_added: number;
  relationships_removed: number;
  details: Record<string, any>;
}

export interface IndexTriggerResponse {
  run_id: string;
  status: string;
  message: string;
}

export interface IndexRunDetailResponse {
  id: string;
  status: string;
  current_stage: string;
  progress_percent: number;
  entities_count: number;
  relationships_count: number;
  duration_seconds: number;
  log_output: string;
  error_message: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface SettingsResponse {
  project_id: string;
  repository_connection_id: string;
  default_branch: string;
  included_paths: string[];
  excluded_paths: string[];
  max_file_size_kb: number;
  auto_index_on_sync: boolean;
}

export interface SettingsUpdateRequest {
  repository_connection_id: string;
  default_branch?: string;
  included_paths?: string[];
  excluded_paths?: string[];
  max_file_size_kb?: number;
  auto_index_on_sync?: boolean;
}
