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


class IngestRepositoryRequest(BaseModel):
    path: str = ""


class CodeSymbolSchema(BaseModel):
    name: str
    kind: str
    line: int


class CodeFileSchema(BaseModel):
    path: str
    language: str
    symbols: list[CodeSymbolSchema] = []


class IngestRepositoryResponse(BaseModel):
    connected: bool
    detail: str
    files_scanned: int = 0
    symbols_found: int = 0
    nodes_synced: int = 0
    relationships_synced: int = 0
    synced_at: datetime | None = None
    commit_sha: str = ""


class CodeGraphResponse(BaseModel):
    connected: bool
    detail: str
    files: list[CodeFileSchema] = []
