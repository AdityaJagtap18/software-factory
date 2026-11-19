from app.services.agent_runtime.adapters import (
    ClaudeCodeAdapter,
    CodexAdapter,
    CustomAdapter,
    GeminiCliAdapter,
)
from app.services.agent_runtime.base import CodingAgentRuntimeAdapter

_ADAPTERS: dict[str, CodingAgentRuntimeAdapter] = {
    adapter.slug: adapter
    for adapter in (ClaudeCodeAdapter(), CodexAdapter(), GeminiCliAdapter(), CustomAdapter())
}


def all_adapters() -> list[CodingAgentRuntimeAdapter]:
    return list(_ADAPTERS.values())


def get_adapter(slug: str) -> CodingAgentRuntimeAdapter | None:
    return _ADAPTERS.get(slug)
