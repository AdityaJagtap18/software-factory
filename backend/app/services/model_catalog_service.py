"""Model Catalog Service.

Combines registered coding-agent runtimes, configured organization connections,
live runtime health checks, and supported models into a unified, ChatGPT-style
dynamic model catalog.
"""

from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from sqlalchemy.orm import Session as DBSession

from app.core.crypto import decrypt_value
from app.models.agent_runtime import CodingAgentConnection, ConnectionStatus, Credential
from app.schemas.agent_runtime import (
    CapabilitySchema,
    ModelCatalogResponse,
    ModelOption,
    ProviderGroup,
)
from app.services.agent_runtime.registry import all_adapters, get_adapter

logger = logging.getLogger(__name__)

# Provider metadata and model definitions
PROVIDER_SPECS = {
    "claude_code": {
        "provider_id": "anthropic",
        "provider_name": "Anthropic",
        "icon": "agents/coding-agent",
        "models": [
            {
                "model_id": "claude-3-7-sonnet",
                "model_name": "Claude 3.7 Sonnet",
                "display_name": "Claude Code · Sonnet 3.7",
                "description": "Anthropic flagship reasoning & coding model",
            },
            {
                "model_id": "claude-3-5-sonnet",
                "model_name": "Claude 3.5 Sonnet",
                "display_name": "Claude Code · Sonnet 3.5",
                "description": "High performance coding & agentic reasoning",
            },
            {
                "model_id": "claude-3-opus",
                "model_name": "Claude 3 Opus",
                "display_name": "Claude Code · Opus",
                "description": "Deep thinking and complex system design",
            },
            {
                "model_id": "claude-3-5-haiku",
                "model_name": "Claude 3.5 Haiku",
                "display_name": "Claude Code · Haiku",
                "description": "Fast and lightweight code editing",
            },
        ],
    },
    "gemini_cli": {
        "provider_id": "google",
        "provider_name": "Google",
        "icon": "agents/coding-agent",
        "models": [
            {
                "model_id": "gemini-2.5-pro",
                "model_name": "Gemini 2.5 Pro",
                "display_name": "Gemini CLI · 2.5 Pro",
                "description": "Google state-of-the-art coding & long-context agent",
            },
            {
                "model_id": "gemini-2.5-flash",
                "model_name": "Gemini 2.5 Flash",
                "display_name": "Gemini CLI · 2.5 Flash",
                "description": "High-speed coding execution with low latency",
            },
            {
                "model_id": "gemini-1.5-pro",
                "model_name": "Gemini 1.5 Pro",
                "display_name": "Gemini CLI · 1.5 Pro",
                "description": "Established coding model with large context window",
            },
        ],
    },
    "codex": {
        "provider_id": "openai",
        "provider_name": "OpenAI",
        "icon": "agents/coding-agent",
        "models": [
            {
                "model_id": "gpt-4o",
                "model_name": "GPT-4o",
                "display_name": "OpenAI · GPT-4o",
                "description": "Omni-model for multimodal and software engineering",
            },
            {
                "model_id": "o3-mini",
                "model_name": "o3-mini",
                "display_name": "OpenAI · o3-mini",
                "description": "Reasoning model optimized for coding & logic",
            },
            {
                "model_id": "codex-1",
                "model_name": "Codex",
                "display_name": "OpenAI · Codex",
                "description": "OpenAI Codex CLI execution runtime",
            },
        ],
    },
    "ollama": {
        "provider_id": "ollama",
        "provider_name": "Local Models",
        "icon": "navigation/providers",
        "models": [],  # Populated dynamically via Ollama discovery
    },
    "qwen": {
        "provider_id": "qwen",
        "provider_name": "Alibaba Cloud",
        "icon": "agents/coding-agent",
        "models": [
            {
                "model_id": "qwen-2.5-coder-32b",
                "model_name": "Qwen 2.5 Coder 32B",
                "display_name": "Qwen Code · 2.5 Coder",
                "description": "Open-weight coding model with agent tool support",
            },
            {
                "model_id": "qwen-max",
                "model_name": "Qwen Max",
                "display_name": "Qwen Code · Max",
                "description": "Flagship Qwen model via DashScope API",
            },
        ],
    },
    "docker_sandbox": {
        "provider_id": "custom",
        "provider_name": "Custom",
        "icon": "navigation/providers",
        "models": [
            {
                "model_id": "sandbox-bash",
                "model_name": "Isolated Container",
                "display_name": "Docker Sandbox",
                "description": "Zero-network sandboxed bash script runner",
            }
        ],
    },
    "custom": {
        "provider_id": "custom",
        "provider_name": "Custom",
        "icon": "navigation/providers",
        "models": [
            {
                "model_id": "custom-agent",
                "model_name": "Custom Agent",
                "display_name": "Custom Agent",
                "description": "Custom agent runtime via HTTP endpoint",
            }
        ],
    },
}


def get_model_catalog(
    db: DBSession, organization_id: uuid.UUID, current_task_model: Optional[str] = None
) -> ModelCatalogResponse:
    """Builds the dynamic model catalog combining DB configuration and live health checks."""
    existing_connections = (
        db.query(CodingAgentConnection).filter_by(organization_id=organization_id).all()
    )
    conn_map = {c.runtime_slug: c for c in existing_connections}

    all_models: list[ModelOption] = []
    groups_dict: dict[str, ProviderGroup] = {}

    for adapter in all_adapters():
        slug = adapter.slug
        conn = conn_map.get(slug)
        spec = PROVIDER_SPECS.get(
            slug,
            {
                "provider_id": slug,
                "provider_name": adapter.display_name,
                "icon": adapter.icon,
                "models": [{"model_id": f"{slug}-default", "model_name": adapter.display_name, "display_name": adapter.display_name}],
            },
        )

        # Evaluate connection & live health
        credential_value = None
        if conn and conn.credential_id:
            cred = db.get(Credential, conn.credential_id)
            if cred:
                try:
                    credential_value = decrypt_value(cred.encrypted_value)
                except Exception:
                    pass

        # Live health check
        health = adapter.health_check(credential_value)
        is_connected = health.connected or (conn and conn.status == ConnectionStatus.CONNECTED)
        detected_version = health.version or (conn.detected_version if conn else "")

        if is_connected:
            availability = "CONNECTED"
            conn_status = "connected"
            selection_allowed = True
        elif conn and conn.status == ConnectionStatus.ERROR:
            availability = "ERROR"
            conn_status = "error"
            selection_allowed = False
        elif conn:
            availability = "DISCONNECTED"
            conn_status = "not_connected"
            selection_allowed = False
        elif health.connected:
            availability = "AVAILABLE"
            conn_status = "connected"
            selection_allowed = True
        else:
            availability = "UNAVAILABLE"
            conn_status = "not_configured"
            selection_allowed = False

        capabilities_schemas = [
            CapabilitySchema(name=c.name, state=c.state.value) for c in adapter.capabilities()
        ]

        # Determine models for this adapter
        model_list: list[dict] = []
        if slug == "ollama":
            # Dynamic discovery for Ollama models
            supported = adapter.supported_models()
            for m_name in supported:
                clean_name = m_name.replace(":", " ").title()
                model_list.append(
                    {
                        "model_id": m_name,
                        "model_name": clean_name,
                        "display_name": f"Ollama · {clean_name}",
                        "description": "Locally hosted model via Ollama",
                    }
                )
            if not model_list:
                model_list.append(
                    {
                        "model_id": "qwen3:14b",
                        "model_name": "Qwen3 14B",
                        "display_name": "Ollama · Qwen3 14B",
                        "description": "Configured local Ollama model",
                    }
                )
        else:
            model_list = list(spec.get("models", []))

        provider_id = spec["provider_id"]
        provider_name = spec["provider_name"]
        icon = spec["icon"]

        if provider_id not in groups_dict:
            groups_dict[provider_id] = ProviderGroup(
                provider_id=provider_id,
                provider_name=provider_name,
                icon=icon,
                models=[],
            )

        for m in model_list:
            m_id = m["model_id"]
            option_id = f"{slug}:{m_id}"
            is_selected = (current_task_model == m_id) or (current_task_model == option_id)

            opt = ModelOption(
                id=option_id,
                provider_id=provider_id,
                provider_name=provider_name,
                model_id=m_id,
                model_name=m["model_name"],
                runtime_slug=slug,
                runtime_name=adapter.display_name,
                display_name=m.get("display_name", f"{adapter.display_name} · {m['model_name']}"),
                connection_id=conn.id if conn else None,
                connection_status=conn_status,
                availability_status=availability,
                capabilities=capabilities_schemas,
                execution_supported=True,
                selection_allowed=selection_allowed,
                version=detected_version,
                description=m.get("description", ""),
                is_default=is_selected,
            )
            all_models.append(opt)
            groups_dict[provider_id].models.append(opt)

    # Determine default model if none selected
    default_id = None
    if current_task_model:
        matching = next((m for m in all_models if m.model_id == current_task_model or m.id == current_task_model), None)
        if matching:
            default_id = matching.id
            matching.is_default = True

    if not default_id:
        # Prefer first connected Claude, Gemini, or Ollama
        first_connected = next((m for m in all_models if m.selection_allowed and m.runtime_slug in ["claude_code", "gemini_cli", "ollama"]), None)
        if not first_connected:
            first_connected = next((m for m in all_models if m.selection_allowed), None)
        if first_connected:
            default_id = first_connected.id
            first_connected.is_default = True
        elif all_models:
            default_id = all_models[0].id
            all_models[0].is_default = True

    # Filter out empty groups and preserve logical order
    ordered_provider_ids = ["anthropic", "google", "openai", "ollama", "qwen", "custom"]
    ordered_groups: list[ProviderGroup] = []
    for pid in ordered_provider_ids:
        if pid in groups_dict and groups_dict[pid].models:
            ordered_groups.append(groups_dict[pid])
    for pid, grp in groups_dict.items():
        if pid not in ordered_provider_ids and grp.models:
            ordered_groups.append(grp)

    return ModelCatalogResponse(
        groups=ordered_groups,
        models=all_models,
        default_model_id=default_id,
        selected_model_id=default_id,
    )
