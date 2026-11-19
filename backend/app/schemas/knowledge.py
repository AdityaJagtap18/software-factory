from datetime import datetime

from pydantic import BaseModel


class KnowledgeNode(BaseModel):
    id: str
    type: str
    label: str
    properties: dict


class KnowledgeEdge(BaseModel):
    source: str
    target: str
    type: str


class KnowledgeSyncResponse(BaseModel):
    connected: bool
    detail: str
    nodes_synced: int = 0
    relationships_synced: int = 0
    synced_at: datetime | None = None


class KnowledgeGraphResponse(BaseModel):
    connected: bool
    detail: str
    nodes: list[KnowledgeNode] = []
    edges: list[KnowledgeEdge] = []
