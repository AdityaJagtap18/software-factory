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
