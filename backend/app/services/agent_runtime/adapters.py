"""Concrete adapters.

CLI detection shells out to the real binary on PATH; nothing is faked. If a
runtime's CLI is not installed on this machine, `health_check` honestly
returns `connected=False`. Managed-mode checks make a real, minimal call to
the provider's API using the stored credential, so a wrong or revoked key is
reported as not connected rather than assumed to work.
"""

import shutil
import subprocess

import httpx

from app.services.agent_runtime.base import (
    Capability,
    CapabilityState,
    CodingAgentRuntimeAdapter,
    HealthCheckResult,
)

_PROBE_TIMEOUT_SECONDS = 5.0


def _detect_cli_version(binary: str, version_flag: str = "--version") -> HealthCheckResult:
    path = shutil.which(binary)
    if path is None:
        return HealthCheckResult(
            connected=False,
            detail=f"'{binary}' CLI not found on PATH. Install it locally and reconnect.",
        )
    try:
        proc = subprocess.run(
            [binary, version_flag],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return HealthCheckResult(connected=False, detail=f"Failed to execute '{binary}': {exc}")

    if proc.returncode != 0:
        return HealthCheckResult(
            connected=False,
            detail=f"'{binary} {version_flag}' exited with code {proc.returncode}.",
        )
    version = (proc.stdout or proc.stderr).strip().splitlines()[0] if (proc.stdout or proc.stderr) else ""
    return HealthCheckResult(connected=True, version=version, detail=f"Detected '{binary}' on PATH.")


def _probe_anthropic_api(api_key: str) -> HealthCheckResult:
    try:
        resp = httpx.get(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return HealthCheckResult(connected=False, detail=f"Could not reach Anthropic API: {exc}")
    if resp.status_code == 200:
        return HealthCheckResult(connected=True, detail="Anthropic API key verified.")
    return HealthCheckResult(
        connected=False, detail=f"Anthropic API rejected the key (HTTP {resp.status_code})."
    )


def _probe_openai_api(api_key: str) -> HealthCheckResult:
    try:
        resp = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return HealthCheckResult(connected=False, detail=f"Could not reach OpenAI API: {exc}")
    if resp.status_code == 200:
        return HealthCheckResult(connected=True, detail="OpenAI API key verified.")
    return HealthCheckResult(
        connected=False, detail=f"OpenAI API rejected the key (HTTP {resp.status_code})."
    )


def _probe_gemini_api(api_key: str) -> HealthCheckResult:
    try:
        resp = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key},
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return HealthCheckResult(connected=False, detail=f"Could not reach Gemini API: {exc}")
    if resp.status_code == 200:
        return HealthCheckResult(connected=True, detail="Gemini API key verified.")
    return HealthCheckResult(
        connected=False, detail=f"Gemini API rejected the key (HTTP {resp.status_code})."
    )


class ClaudeCodeAdapter(CodingAgentRuntimeAdapter):
    slug = "claude_code"
    display_name = "Claude Code"
    description = "Anthropic coding-agent runtime via Claude Agent SDK / CLI"
    icon = "agents/coding-agent"
    supported_connection_modes = ("local_runtime", "factory_managed")
    auth_method = "Official CLI authentication, or an Anthropic API key"

    def capabilities(self) -> list[Capability]:
        return [
            Capability("Start session", CapabilityState.DECLARED),
            Capability("Resume session", CapabilityState.DECLARED),
            Capability("Stream messages", CapabilityState.DECLARED),
            Capability("CLI detection", CapabilityState.VERIFIED),
        ]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if credential_value:
            return _probe_anthropic_api(credential_value)
        return _detect_cli_version("claude")


class CodexAdapter(CodingAgentRuntimeAdapter):
    slug = "codex"
    display_name = "Codex"
    description = "OpenAI coding-agent runtime via Codex SDK / App Server"
    icon = "agents/coding-agent"
    supported_connection_modes = ("local_runtime", "factory_managed")
    auth_method = "ChatGPT / API key"

    def capabilities(self) -> list[Capability]:
        return [
            Capability("Start thread", CapabilityState.DECLARED),
            Capability("Resume thread", CapabilityState.DECLARED),
            Capability("Stream events", CapabilityState.DECLARED),
            Capability("CLI detection", CapabilityState.VERIFIED),
        ]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if credential_value:
            return _probe_openai_api(credential_value)
        return _detect_cli_version("codex")


class GeminiCliAdapter(CodingAgentRuntimeAdapter):
    slug = "gemini_cli"
    display_name = "Gemini CLI"
    description = "Google coding-agent runtime"
    icon = "agents/coding-agent"
    supported_connection_modes = ("local_runtime", "factory_managed")
    auth_method = "Supported provider authentication"

    def capabilities(self) -> list[Capability]:
        return [
            Capability("Start session", CapabilityState.DECLARED),
            Capability("Stream events", CapabilityState.DECLARED),
            Capability("CLI detection", CapabilityState.VERIFIED),
        ]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if credential_value:
            return _probe_gemini_api(credential_value)
        return _detect_cli_version("gemini")


class CustomAdapter(CodingAgentRuntimeAdapter):
    slug = "custom"
    display_name = "Custom Agent"
    description = "Adapter implementing the common Agent Runtime Interface"
    icon = "navigation/providers"
    supported_connection_modes = ("custom_adapter",)
    auth_method = "Configured credential"

    def capabilities(self) -> list[Capability]:
        return [Capability("Depends on adapter", CapabilityState.DECLARED)]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if not credential_value:
            return HealthCheckResult(
                connected=False, detail="No endpoint configured for this custom adapter."
            )
        try:
            resp = httpx.get(credential_value, timeout=_PROBE_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            return HealthCheckResult(connected=False, detail=f"Could not reach endpoint: {exc}")
        if resp.status_code < 400:
            return HealthCheckResult(connected=True, detail=f"Endpoint responded (HTTP {resp.status_code}).")
        return HealthCheckResult(connected=False, detail=f"Endpoint returned HTTP {resp.status_code}.")
