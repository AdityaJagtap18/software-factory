from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.agent_runtime import ConnectionMode, ConnectionStatus


class CapabilitySchema(BaseModel):
    name: str
    state: str


class RuntimeCatalogEntry(BaseModel):
    """Static metadata for a runtime adapter — not org-specific."""

    slug: str
    name: str
    description: str
    icon: str
    supported_connection_modes: list[str]
    auth_method: str
    capabilities: list[CapabilitySchema]


class ConnectionCreate(BaseModel):
    runtime_slug: str
    connection_mode: ConnectionMode
    credential_name: str | None = None
    credential_provider: str | None = None
    credential_value: str | None = Field(default=None, repr=False)


class ConnectionResponse(BaseModel):
    id: UUID | None
    is_configured: bool
    organization_id: UUID
    runtime_slug: str
    runtime_name: str
    icon: str
    description: str
    connection_mode: ConnectionMode | None
    auth_method: str
    status: ConnectionStatus
    detected_version: str
    last_error: str
    last_health_check_at: datetime | None
    has_credential: bool
    capabilities: list[CapabilitySchema]

    model_config = {"from_attributes": True}
