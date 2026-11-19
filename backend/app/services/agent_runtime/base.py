"""The Common Agent Runtime Interface.

Every coding-agent runtime (Claude Code, Codex, Gemini CLI, a custom adapter)
is exposed to the rest of the platform through this interface. An adapter
never claims a connection is live without having actually performed the
check described in `health_check`: the health check is the only source of
truth for `connected` / `version`. Nothing here simulates success.
"""

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


class CapabilityState(str, enum.Enum):
    """How confident the platform is that a capability actually works.

    DECLARED: the adapter author asserts the runtime supports this.
    TESTED: an automated check has exercised it at least once.
    VERIFIED: it is exercised by this health check on every run.
    Only VERIFIED capabilities should be treated as guaranteed.
    """

    DECLARED = "declared"
    TESTED = "tested"
    VERIFIED = "verified"


@dataclass(frozen=True)
class Capability:
    name: str
    state: CapabilityState


@dataclass(frozen=True)
class HealthCheckResult:
    connected: bool
    version: str = ""
    detail: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CodingAgentRuntimeAdapter(ABC):
    """Base class every runtime adapter implements."""

    slug: str
    display_name: str
    description: str
    icon: str
    supported_connection_modes: tuple[str, ...]
    auth_method: str

    @abstractmethod
    def capabilities(self) -> list[Capability]:
        """Static capability metadata for this runtime, with honest validation states."""

    @abstractmethod
    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        """Perform a real check (CLI detection and/or a live API probe).

        Must never return `connected=True` without having actually observed
        evidence of a working runtime in this call.
        """
