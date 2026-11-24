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
from typing import Callable


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


@dataclass(frozen=True)
class ExecutionResult:
    succeeded: bool
    output: str = ""
    error: str = ""


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

    def supported_models(self) -> list[str]:
        """List of supported or detected models for this runtime."""
        return []

    @abstractmethod
    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        """Perform a real check (CLI detection and/or a live API probe).

        Must never return `connected=True` without having actually observed
        evidence of a working runtime in this call.
        """

    @abstractmethod
    def start_execution(
        self, prompt: str, credential_value: str | None, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        """Hand a task prompt to the real runtime and return its real output.

        `cwd`, when given (Phase 14), is a real, isolated Git worktree the
        task should run against -- a local-CLI adapter runs the CLI there
        so its real filesystem edits land in that checkout; a hosted-API
        adapter has no filesystem to run in and honestly ignores it rather
        than pretending to use it.

        Must never return `succeeded=True` with fabricated output. If the
        runtime cannot actually be reached (CLI missing, no credential,
        provider error), this returns `succeeded=False` with an honest
        `error` describing what actually happened.
        """

    def start_execution_streaming(
        self,
        prompt: str,
        credential_value: str | None,
        on_chunk: Callable[[str], None],
        should_cancel: Callable[[], bool],
        cwd: str | None = None,
        model: str | None = None,
    ) -> ExecutionResult:
        """Like `start_execution`, but calls `on_chunk` as real output arrives
        (subprocess stdout lines, or provider SSE deltas) and checks
        `should_cancel` between chunks to stop early on a real cancellation.

        The default implementation (used by adapters with nothing
        incremental to stream, e.g. a plain HTTP custom adapter) just runs
        the whole thing and emits one chunk — it never fabricates partial
        progress that didn't happen.
        """
        result = self.start_execution(prompt, credential_value, cwd, model=model)
        if result.output:
            on_chunk(result.output)
        return result
