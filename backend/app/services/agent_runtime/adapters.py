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
    ExecutionResult,
    HealthCheckResult,
)

_PROBE_TIMEOUT_SECONDS = 5.0
_EXECUTION_TIMEOUT_SECONDS = 120.0
_MAX_OUTPUT_CHARS = 20_000


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


def _run_cli_prompt(binary: str, prompt_flag: str, prompt: str) -> ExecutionResult:
    """Invoke a locally installed coding-agent CLI non-interactively.

    Exact non-interactive flags are documented by each CLI and may change
    between versions; if the installed binary rejects `prompt_flag`, that
    real failure is reported honestly rather than silently retried with a
    guessed alternative.
    """
    path = shutil.which(binary)
    if path is None:
        return ExecutionResult(
            succeeded=False,
            error=f"'{binary}' CLI not found on PATH. Install it locally and reconnect.",
        )
    try:
        proc = subprocess.run(
            [binary, prompt_flag, prompt],
            capture_output=True,
            text=True,
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ExecutionResult(succeeded=False, error=f"Failed to execute '{binary}': {exc}")

    if proc.returncode != 0:
        return ExecutionResult(
            succeeded=False,
            error=(proc.stderr or proc.stdout or f"'{binary}' exited with code {proc.returncode}")[
                :_MAX_OUTPUT_CHARS
            ],
        )
    return ExecutionResult(succeeded=True, output=(proc.stdout or "")[:_MAX_OUTPUT_CHARS])


def _run_cli_prompt_streaming(
    binary: str, prompt_flag: str, prompt: str, on_chunk, should_cancel
) -> ExecutionResult:
    """Like `_run_cli_prompt`, but reads the real child process's stdout line
    by line as it's produced and can terminate it early on real cancellation.
    """
    path = shutil.which(binary)
    if path is None:
        return ExecutionResult(
            succeeded=False,
            error=f"'{binary}' CLI not found on PATH. Install it locally and reconnect.",
        )
    try:
        proc = subprocess.Popen(
            [binary, prompt_flag, prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return ExecutionResult(succeeded=False, error=f"Failed to execute '{binary}': {exc}")

    collected: list[str] = []
    cancelled = False
    assert proc.stdout is not None
    for line in proc.stdout:
        collected.append(line)
        on_chunk(line)
        if should_cancel():
            cancelled = True
            proc.terminate()
            break
    proc.wait(timeout=_PROBE_TIMEOUT_SECONDS if cancelled else None)

    output = "".join(collected)[:_MAX_OUTPUT_CHARS]
    if cancelled:
        return ExecutionResult(succeeded=False, output=output, error="Cancelled by user.")
    if proc.returncode != 0:
        return ExecutionResult(
            succeeded=False, error=output or f"'{binary}' exited with code {proc.returncode}"
        )
    return ExecutionResult(succeeded=True, output=output)


def _run_anthropic_prompt(api_key: str, prompt: str) -> ExecutionResult:
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return ExecutionResult(succeeded=False, error=f"Could not reach Anthropic API: {exc}")
    if resp.status_code != 200:
        return ExecutionResult(
            succeeded=False, error=f"Anthropic API returned HTTP {resp.status_code}: {resp.text[:500]}"
        )
    data = resp.json()
    text = "".join(block.get("text", "") for block in data.get("content", []))
    return ExecutionResult(succeeded=True, output=text[:_MAX_OUTPUT_CHARS])


def _run_anthropic_prompt_streaming(
    api_key: str, prompt: str, on_chunk, should_cancel
) -> ExecutionResult:
    """Real Anthropic SSE streaming (`"stream": true`) — each `text_delta`
    event is a genuine token chunk from the provider, emitted as it arrives.
    """
    collected: list[str] = []
    try:
        with httpx.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
            },
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                resp.read()
                return ExecutionResult(
                    succeeded=False,
                    error=f"Anthropic API returned HTTP {resp.status_code}: {resp.text[:500]}",
                )
            import json as _json

            for line in resp.iter_lines():
                if should_cancel():
                    return ExecutionResult(
                        succeeded=False, output="".join(collected), error="Cancelled by user."
                    )
                if not line.startswith("data: "):
                    continue
                try:
                    event = _json.loads(line[len("data: ") :])
                except ValueError:
                    continue
                if event.get("type") == "content_block_delta":
                    text = event.get("delta", {}).get("text", "")
                    if text:
                        collected.append(text)
                        on_chunk(text)
    except httpx.HTTPError as exc:
        return ExecutionResult(
            succeeded=False, output="".join(collected), error=f"Could not reach Anthropic API: {exc}"
        )
    return ExecutionResult(succeeded=True, output="".join(collected)[:_MAX_OUTPUT_CHARS])


def _run_openai_prompt(api_key: str, prompt: str) -> ExecutionResult:
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]},
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return ExecutionResult(succeeded=False, error=f"Could not reach OpenAI API: {exc}")
    if resp.status_code != 200:
        return ExecutionResult(
            succeeded=False, error=f"OpenAI API returned HTTP {resp.status_code}: {resp.text[:500]}"
        )
    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        text = ""
    return ExecutionResult(succeeded=True, output=text[:_MAX_OUTPUT_CHARS])


def _run_openai_prompt_streaming(
    api_key: str, prompt: str, on_chunk, should_cancel
) -> ExecutionResult:
    """Real OpenAI SSE streaming (`"stream": true`) — each delta is a
    genuine token chunk from the provider, emitted as it arrives.
    """
    collected: list[str] = []
    try:
        with httpx.stream(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
            },
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                resp.read()
                return ExecutionResult(
                    succeeded=False,
                    error=f"OpenAI API returned HTTP {resp.status_code}: {resp.text[:500]}",
                )
            import json as _json

            for line in resp.iter_lines():
                if should_cancel():
                    return ExecutionResult(
                        succeeded=False, output="".join(collected), error="Cancelled by user."
                    )
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: ") :]
                if payload == "[DONE]":
                    break
                try:
                    event = _json.loads(payload)
                    text = event["choices"][0]["delta"].get("content") or ""
                except (ValueError, KeyError, IndexError):
                    continue
                if text:
                    collected.append(text)
                    on_chunk(text)
    except httpx.HTTPError as exc:
        return ExecutionResult(
            succeeded=False, output="".join(collected), error=f"Could not reach OpenAI API: {exc}"
        )
    return ExecutionResult(succeeded=True, output="".join(collected)[:_MAX_OUTPUT_CHARS])


def _run_gemini_prompt(api_key: str, prompt: str) -> ExecutionResult:
    try:
        resp = httpx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return ExecutionResult(succeeded=False, error=f"Could not reach Gemini API: {exc}")
    if resp.status_code != 200:
        return ExecutionResult(
            succeeded=False, error=f"Gemini API returned HTTP {resp.status_code}: {resp.text[:500]}"
        )
    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        text = ""
    return ExecutionResult(succeeded=True, output=text[:_MAX_OUTPUT_CHARS])


def _run_gemini_prompt_streaming(
    api_key: str, prompt: str, on_chunk, should_cancel
) -> ExecutionResult:
    """Real Gemini SSE streaming (`alt=sse` on `:streamGenerateContent`) —
    each candidate text part is a genuine chunk from the provider.
    """
    collected: list[str] = []
    try:
        with httpx.stream(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:streamGenerateContent",
            params={"key": api_key, "alt": "sse"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                resp.read()
                return ExecutionResult(
                    succeeded=False,
                    error=f"Gemini API returned HTTP {resp.status_code}: {resp.text[:500]}",
                )
            import json as _json

            for line in resp.iter_lines():
                if should_cancel():
                    return ExecutionResult(
                        succeeded=False, output="".join(collected), error="Cancelled by user."
                    )
                if not line.startswith("data: "):
                    continue
                try:
                    event = _json.loads(line[len("data: ") :])
                    text = event["candidates"][0]["content"]["parts"][0]["text"]
                except (ValueError, KeyError, IndexError):
                    continue
                if text:
                    collected.append(text)
                    on_chunk(text)
    except httpx.HTTPError as exc:
        return ExecutionResult(
            succeeded=False, output="".join(collected), error=f"Could not reach Gemini API: {exc}"
        )
    return ExecutionResult(succeeded=True, output="".join(collected)[:_MAX_OUTPUT_CHARS])


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
            Capability("Stream messages", CapabilityState.TESTED),
            Capability("CLI detection", CapabilityState.VERIFIED),
        ]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if credential_value:
            return _probe_anthropic_api(credential_value)
        return _detect_cli_version("claude")

    def start_execution(self, prompt: str, credential_value: str | None) -> ExecutionResult:
        if credential_value:
            return _run_anthropic_prompt(credential_value, prompt)
        return _run_cli_prompt("claude", "-p", prompt)

    def start_execution_streaming(self, prompt, credential_value, on_chunk, should_cancel) -> ExecutionResult:
        if credential_value:
            return _run_anthropic_prompt_streaming(credential_value, prompt, on_chunk, should_cancel)
        return _run_cli_prompt_streaming("claude", "-p", prompt, on_chunk, should_cancel)


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
            Capability("Stream events", CapabilityState.TESTED),
            Capability("CLI detection", CapabilityState.VERIFIED),
        ]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if credential_value:
            return _probe_openai_api(credential_value)
        return _detect_cli_version("codex")

    def start_execution(self, prompt: str, credential_value: str | None) -> ExecutionResult:
        if credential_value:
            return _run_openai_prompt(credential_value, prompt)
        return _run_cli_prompt("codex", "exec", prompt)

    def start_execution_streaming(self, prompt, credential_value, on_chunk, should_cancel) -> ExecutionResult:
        if credential_value:
            return _run_openai_prompt_streaming(credential_value, prompt, on_chunk, should_cancel)
        return _run_cli_prompt_streaming("codex", "exec", prompt, on_chunk, should_cancel)


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
            Capability("Stream events", CapabilityState.TESTED),
            Capability("CLI detection", CapabilityState.VERIFIED),
        ]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if credential_value:
            return _probe_gemini_api(credential_value)
        return _detect_cli_version("gemini")

    def start_execution(self, prompt: str, credential_value: str | None) -> ExecutionResult:
        if credential_value:
            return _run_gemini_prompt(credential_value, prompt)
        return _run_cli_prompt("gemini", "-p", prompt)

    def start_execution_streaming(self, prompt, credential_value, on_chunk, should_cancel) -> ExecutionResult:
        if credential_value:
            return _run_gemini_prompt_streaming(credential_value, prompt, on_chunk, should_cancel)
        return _run_cli_prompt_streaming("gemini", "-p", prompt, on_chunk, should_cancel)


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

    def start_execution(self, prompt: str, credential_value: str | None) -> ExecutionResult:
        if not credential_value:
            return ExecutionResult(succeeded=False, error="No endpoint configured for this custom adapter.")
        try:
            resp = httpx.post(credential_value, json={"prompt": prompt}, timeout=_EXECUTION_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            return ExecutionResult(succeeded=False, error=f"Could not reach endpoint: {exc}")
        if resp.status_code >= 400:
            return ExecutionResult(succeeded=False, error=f"Endpoint returned HTTP {resp.status_code}.")
        return ExecutionResult(succeeded=True, output=resp.text[:_MAX_OUTPUT_CHARS])
