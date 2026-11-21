from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.agent_runtime import ConnectionMode, ConnectionStatus


class CapabilitySchema(BaseModel):
    name: str
    state: str


class AgentResponse(BaseModel):
    """Phase 2 (P2-4) Agent Registry read model."""

    id: UUID
    slug: str
    name: str
    description: str
    version: str
    status: str
    capabilities: list[CapabilitySchema]

    model_config = {"from_attributes": True}


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


class ModelOption(BaseModel):
    id: str  # Composite identifier: e.g. "claude_code:claude-3-7-sonnet"
    provider_id: str  # "anthropic", "google", "openai", "ollama", "qwen", "custom"
    provider_name: str  # "Anthropic", "Google", "OpenAI", "Local Models", "Custom"
    model_id: str  # "claude-3-7-sonnet", "gemini-2.5-pro", etc.
    model_name: str  # "Claude 3.7 Sonnet", "Gemini 2.5 Pro", etc.
    runtime_slug: str  # "claude_code", "gemini_cli", etc.
    runtime_name: str  # "Claude Code", "Gemini CLI", etc.
    display_name: str  # "Claude Code · Sonnet 3.7"
    connection_id: UUID | None = None
    connection_status: str  # "connected", "not_configured", "not_connected", "error"
    availability_status: str  # "CONNECTED", "AVAILABLE", "DISCONNECTED", "UNAVAILABLE", "MISCONFIGURED", "ERROR"
    capabilities: list[CapabilitySchema] = Field(default_factory=list)
    execution_supported: bool = True
    selection_allowed: bool = False
    version: str = ""
    description: str = ""
    is_default: bool = False


class ProviderGroup(BaseModel):
    provider_id: str
    provider_name: str
    icon: str
    models: list[ModelOption]


class ModelCatalogResponse(BaseModel):
    groups: list[ProviderGroup]
    models: list[ModelOption]
    default_model_id: str | None = None
    selected_model_id: str | None = None

