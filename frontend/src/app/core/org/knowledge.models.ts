export interface KnowledgeNode {
  id: string;
  type: string;
  label: string;
  properties: Record<string, unknown>;
}

export interface KnowledgeEdge {
  source: string;
  target: string;
  type: string;
}

export interface KnowledgeSyncResponse {
  connected: boolean;
  detail: string;
  nodes_synced: number;
  relationships_synced: number;
  synced_at: string | null;
}

export interface KnowledgeGraphResponse {
  connected: boolean;
  detail: string;
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
}

export interface CodeSymbol {
  name: string;
  kind: string;
  line: number;
}

export interface CodeFile {
  path: string;
  language: string;
  symbols: CodeSymbol[];
}

export interface IngestRepositoryResponse {
  connected: boolean;
  detail: string;
  files_scanned: number;
  symbols_found: number;
  nodes_synced: number;
  relationships_synced: number;
  synced_at: string | null;
}

export interface CodeGraphResponse {
  connected: boolean;
  detail: string;
  files: CodeFile[];
}
