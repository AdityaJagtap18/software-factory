"""Concrete adapters.

CLI detection shells out to the real binary on PATH; nothing is faked. If a
runtime's CLI is not installed on this machine, `health_check` honestly
returns `connected=False`. Managed-mode checks make a real, minimal call to
the provider's API using the stored credential, so a wrong or revoked key is
reported as not connected rather than assumed to work.
"""

import os
import shutil
import subprocess
from pathlib import Path

import httpx

from app.core.config import get_settings
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
            [path, version_flag],
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


def _run_cli_prompt(
    binary: str,
    prompt_flag: str,
    prompt: str,
    cwd: str | None = None,
    extra_args: list[str] | None = None,
    env: dict | None = None,
) -> ExecutionResult:
    """Invoke a locally installed coding-agent CLI non-interactively.

    Exact non-interactive flags are documented by each CLI and may change
    between versions; if the installed binary rejects `prompt_flag`, that
    real failure is reported honestly rather than silently retried with a
    guessed alternative. `cwd`, when given, runs the CLI inside a real Git
    worktree (Phase 14) so any files it edits land there for real.

    `extra_args`, when given, is appended verbatim after the prompt --
    used for a CLI's own non-interactive permission flag (see
    `ClaudeCodeAdapter`), scoped by the caller to only apply when a real
    worktree `cwd` bounds where edits can land.
    """
    path = shutil.which(binary)
    if path is None:
        return ExecutionResult(
            succeeded=False,
            error=f"'{binary}' CLI not found on PATH. Install it locally and reconnect.",
        )
    full_env = {**os.environ, **env} if env else None
    try:
        proc = subprocess.run(
            [path, prompt_flag, prompt, *(extra_args or [])],
            capture_output=True,
            text=True,
            timeout=_EXECUTION_TIMEOUT_SECONDS,
            cwd=cwd,
            env=full_env,
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
    binary: str,
    prompt_flag: str,
    prompt: str,
    on_chunk,
    should_cancel,
    cwd: str | None = None,
    extra_args: list[str] | None = None,
    env: dict | None = None,
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
    full_env = {**os.environ, **env} if env else None
    try:
        proc = subprocess.Popen(
            [path, prompt_flag, prompt, *(extra_args or [])],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=cwd,
            env=full_env,
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


def _run_anthropic_prompt(api_key: str, prompt: str, model: str | None = None) -> ExecutionResult:
    target_model = model or "claude-3-5-haiku-20241022"
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": target_model,
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
    api_key: str, prompt: str, on_chunk, should_cancel, model: str | None = None
) -> ExecutionResult:
    """Real Anthropic SSE streaming (`"stream": true`) — each `text_delta`
    event is a genuine token chunk from the provider, emitted as it arrives.
    """
    target_model = model or "claude-3-5-haiku-20241022"
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
                "model": target_model,
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


def _run_openai_prompt(api_key: str, prompt: str, model: str | None = None) -> ExecutionResult:
    target_model = model or "gpt-4o-mini"
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={"model": target_model, "messages": [{"role": "user", "content": prompt}]},
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
    api_key: str, prompt: str, on_chunk, should_cancel, model: str | None = None
) -> ExecutionResult:
    """Real OpenAI SSE streaming (`"stream": true`) — each delta is a
    genuine token chunk from the provider, emitted as it arrives.
    """
    target_model = model or "gpt-4o-mini"
    collected: list[str] = []
    try:
        with httpx.stream(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": target_model,
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


_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_QWEN_MODEL = "qwen-plus"


def _run_qwen_prompt(api_key: str, prompt: str) -> ExecutionResult:
    try:
        resp = httpx.post(
            f"{_DASHSCOPE_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={"model": _QWEN_MODEL, "messages": [{"role": "user", "content": prompt}]},
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return ExecutionResult(succeeded=False, error=f"Could not reach DashScope (Qwen) API: {exc}")
    if resp.status_code != 200:
        return ExecutionResult(
            succeeded=False, error=f"DashScope (Qwen) API returned HTTP {resp.status_code}: {resp.text[:500]}"
        )
    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        text = ""
    return ExecutionResult(succeeded=True, output=text[:_MAX_OUTPUT_CHARS])


def _run_qwen_prompt_streaming(api_key: str, prompt: str, on_chunk, should_cancel) -> ExecutionResult:
    """Real DashScope SSE streaming via its OpenAI-compatible endpoint --
    each delta is a genuine token chunk from the provider."""
    collected: list[str] = []
    try:
        with httpx.stream(
            "POST",
            f"{_DASHSCOPE_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json={
                "model": _QWEN_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
            },
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                resp.read()
                return ExecutionResult(
                    succeeded=False,
                    error=f"DashScope (Qwen) API returned HTTP {resp.status_code}: {resp.text[:500]}",
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
            succeeded=False, output="".join(collected), error=f"Could not reach DashScope (Qwen) API: {exc}"
        )
    return ExecutionResult(succeeded=True, output="".join(collected)[:_MAX_OUTPUT_CHARS])


def _probe_qwen_api(api_key: str) -> HealthCheckResult:
    try:
        resp = httpx.get(
            f"{_DASHSCOPE_BASE_URL}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return HealthCheckResult(connected=False, detail=f"Could not reach DashScope (Qwen) API: {exc}")
    if resp.status_code == 200:
        return HealthCheckResult(connected=True, detail="DashScope (Qwen) API key verified.")
    return HealthCheckResult(
        connected=False, detail=f"DashScope (Qwen) API rejected the key (HTTP {resp.status_code})."
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


def _claude_code_permission_args(cwd: str | None) -> list[str]:
    """Running `claude -p` with no TTY to approve a prompt, the CLI
    defaults to *denying* file-editing tools rather than guessing --
    a task would otherwise report success without ever writing a file.
    `acceptEdits` auto-approves file reads/writes/edits only; it still
    gates Bash. Only applied when `cwd` bounds the edit to a real,
    isolated task worktree (Phase 14) -- never for a bare prompt with no
    codebase, where there'd be no directory to scope it to."""
    return ["--permission-mode", "acceptEdits"] if cwd else []


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

    def supported_models(self) -> list[str]:
        return [
            "claude-3-7-sonnet",
            "claude-3-5-sonnet",
            "claude-3-opus",
            "claude-3-5-haiku",
        ]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if credential_value:
            return _probe_anthropic_api(credential_value)
        return _detect_cli_version("claude")

    def start_execution(
        self, prompt: str, credential_value: str | None, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        if credential_value:
            return _run_anthropic_prompt(credential_value, prompt, model=model)
        extra = list(_claude_code_permission_args(cwd))
        if model:
            extra.extend(["--model", model])
        sandbox_image = get_settings().claude_code_sandbox_image
        if sandbox_image:
            return _run_cli_prompt_sandboxed(sandbox_image, "claude", "-p", prompt, cwd, extra_args=extra)
        return _run_cli_prompt("claude", "-p", prompt, cwd, extra_args=extra)

    def start_execution_streaming(
        self, prompt, credential_value, on_chunk, should_cancel, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        if credential_value:
            return _run_anthropic_prompt_streaming(
                credential_value, prompt, on_chunk, should_cancel, model=model
            )
        extra = list(_claude_code_permission_args(cwd))
        if model:
            extra.extend(["--model", model])
        sandbox_image = get_settings().claude_code_sandbox_image
        if sandbox_image:
            return _run_cli_prompt_streaming_sandboxed(
                sandbox_image, "claude", "-p", prompt, on_chunk, should_cancel, cwd, extra_args=extra
            )
        return _run_cli_prompt_streaming(
            "claude", "-p", prompt, on_chunk, should_cancel, cwd, extra_args=extra
        )


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

    def supported_models(self) -> list[str]:
        return ["gpt-4o", "o3-mini", "codex-1"]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if credential_value:
            return _probe_openai_api(credential_value)
        return _detect_cli_version("codex")

    def start_execution(
        self, prompt: str, credential_value: str | None, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        if credential_value:
            return _run_openai_prompt(credential_value, prompt, model=model)
        extra = ["--model", model] if model else None
        sandbox_image = get_settings().codex_sandbox_image
        if sandbox_image:
            return _run_cli_prompt_sandboxed(sandbox_image, "codex", "exec", prompt, cwd, extra_args=extra)
        return _run_cli_prompt("codex", "exec", prompt, cwd, extra_args=extra)

    def start_execution_streaming(
        self, prompt, credential_value, on_chunk, should_cancel, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        if credential_value:
            return _run_openai_prompt_streaming(
                credential_value, prompt, on_chunk, should_cancel, model=model
            )
        extra = ["--model", model] if model else None
        sandbox_image = get_settings().codex_sandbox_image
        if sandbox_image:
            return _run_cli_prompt_streaming_sandboxed(
                sandbox_image, "codex", "exec", prompt, on_chunk, should_cancel, cwd, extra_args=extra
            )
        return _run_cli_prompt_streaming(
            "codex", "exec", prompt, on_chunk, should_cancel, cwd, extra_args=extra
        )


def _gemini_cli_extra_args(cwd: str | None) -> list[str]:
    # Trust the workspace and enable auto-approval of edit tools so Gemini CLI
    # can actually modify files in the task worktree non-interactively
    return ["--skip-trust", "-y"] if cwd else ["--skip-trust"]


def _resolve_gemini_api_key(credential_value: str | None) -> str:
    if credential_value:
        return credential_value.strip()
    settings = get_settings()
    if hasattr(settings, "gemini_api_key") and settings.gemini_api_key:
        return settings.gemini_api_key.strip()
    return os.environ.get("GEMINI_API_KEY", "").strip()


class GeminiCliAdapter(CodingAgentRuntimeAdapter):
    slug = "gemini_cli"
    display_name = "Gemini CLI"
    description = "Google coding-agent runtime via Gemini CLI"
    icon = "agents/coding-agent"
    supported_connection_modes = ("local_runtime", "factory_managed")
    auth_method = "Gemini API key or GEMINI_API_KEY environment variable"

    def capabilities(self) -> list[Capability]:
        return [
            Capability("Start session", CapabilityState.DECLARED),
            Capability("Stream events", CapabilityState.TESTED),
            Capability("CLI detection", CapabilityState.VERIFIED),
        ]

    def supported_models(self) -> list[str]:
        return ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-pro"]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        cli_check = _detect_cli_version("gemini")
        if not cli_check.connected:
            return cli_check

        api_key = _resolve_gemini_api_key(credential_value)
        if api_key:
            probe = _probe_gemini_api(api_key)
            if not probe.connected:
                return HealthCheckResult(
                    connected=False,
                    version=cli_check.version,
                    detail=f"Detected 'gemini' {cli_check.version} on PATH, but authentication failed: {probe.detail}",
                )
            return HealthCheckResult(
                connected=True,
                version=cli_check.version,
                detail=f"Detected 'gemini' {cli_check.version} on PATH with verified API authentication.",
            )

        return HealthCheckResult(
            connected=True,
            version=cli_check.version,
            detail=f"Detected 'gemini' {cli_check.version} on PATH.",
        )

    def start_execution(
        self, prompt: str, credential_value: str | None, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        api_key = _resolve_gemini_api_key(credential_value)
        env = {"GEMINI_API_KEY": api_key} if api_key else None
        extra = list(_gemini_cli_extra_args(cwd))
        if model:
            extra.extend(["-m", model])
        sandbox_image = get_settings().gemini_cli_sandbox_image
        if sandbox_image:
            return _run_cli_prompt_sandboxed(
                sandbox_image, "gemini", "-p", prompt, cwd=cwd, extra_args=extra, env=env
            )
        return _run_cli_prompt(
            "gemini", "-p", prompt, cwd=cwd, extra_args=extra, env=env
        )

    def start_execution_streaming(
        self, prompt, credential_value, on_chunk, should_cancel, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        api_key = _resolve_gemini_api_key(credential_value)
        env = {"GEMINI_API_KEY": api_key} if api_key else None
        extra = list(_gemini_cli_extra_args(cwd))
        if model:
            extra.extend(["-m", model])
        sandbox_image = get_settings().gemini_cli_sandbox_image
        if sandbox_image:
            return _run_cli_prompt_streaming_sandboxed(
                sandbox_image, "gemini", "-p", prompt, on_chunk, should_cancel, cwd=cwd, extra_args=extra, env=env
            )
        return _run_cli_prompt_streaming(
            "gemini", "-p", prompt, on_chunk, should_cancel, cwd=cwd, extra_args=extra, env=env
        )


class QwenAdapter(CodingAgentRuntimeAdapter):
    slug = "qwen"
    display_name = "Qwen"
    description = "Alibaba Qwen coding-agent runtime via local Ollama or Qwen CLI / DashScope API"
    icon = "agents/coding-agent"
    supported_connection_modes = ("local_runtime", "factory_managed")
    auth_method = "Local Ollama Qwen model, CLI authentication, or a DashScope API key"

    def capabilities(self) -> list[Capability]:
        return [
            Capability("Start session", CapabilityState.DECLARED),
            Capability("Stream events", CapabilityState.TESTED),
            Capability("CLI detection", CapabilityState.VERIFIED),
        ]

    def supported_models(self) -> list[str]:
        return ["qwen3:14b", "qwen-2.5-coder-32b", "qwen-max"]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        if credential_value:
            return _probe_qwen_api(credential_value)
        cli_check = _detect_cli_version("qwen")
        if cli_check.connected:
            return cli_check
        # Fall back to local Ollama if running with a Qwen model
        try:
            ollama_health, models = _probe_ollama_api(_OLLAMA_DEFAULT_URL)
            if ollama_health.connected:
                qwen_models = [m for m in models if "qwen" in m.lower()]
                if qwen_models:
                    return HealthCheckResult(
                        connected=True,
                        version=f"Qwen ({qwen_models[0]} via {ollama_health.version})",
                        detail=f"Qwen model '{qwen_models[0]}' is running locally on Ollama at {_OLLAMA_DEFAULT_URL}.",
                    )
        except Exception:
            pass
        return cli_check

    def start_execution(
        self, prompt: str, credential_value: str | None, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        if credential_value:
            return _run_qwen_prompt(credential_value, prompt)
        sandbox_image = get_settings().qwen_sandbox_image
        if sandbox_image:
            # The CLI's presence is a property of the sandbox image now,
            # not the backend host's own PATH -- skip the host-side
            # `shutil.which` check that only makes sense for direct
            # host execution.
            extra = ["--model", model] if model else None
            return _run_cli_prompt_sandboxed(sandbox_image, "qwen", "-p", prompt, cwd, extra_args=extra)
        if shutil.which("qwen"):
            extra = ["--model", model] if model else None
            return _run_cli_prompt("qwen", "-p", prompt, cwd, extra_args=extra)
        # Execute via local Ollama Qwen runtime
        return _run_ollama_prompt(
            _OLLAMA_DEFAULT_URL,
            model or "qwen3:14b",
            prompt,
            cwd=cwd,
        )

    def start_execution_streaming(
        self, prompt, credential_value, on_chunk, should_cancel, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        if credential_value:
            return _run_qwen_prompt_streaming(credential_value, prompt, on_chunk, should_cancel)
        sandbox_image = get_settings().qwen_sandbox_image
        if sandbox_image:
            extra = ["--model", model] if model else None
            return _run_cli_prompt_streaming_sandboxed(
                sandbox_image, "qwen", "-p", prompt, on_chunk, should_cancel, cwd, extra_args=extra
            )
        if shutil.which("qwen"):
            extra = ["--model", model] if model else None
            return _run_cli_prompt_streaming(
                "qwen", "-p", prompt, on_chunk, should_cancel, cwd, extra_args=extra
            )
        # Stream via local Ollama Qwen runtime
        return _run_ollama_prompt_streaming(
            _OLLAMA_DEFAULT_URL,
            model or "qwen3:14b",
            prompt,
            on_chunk,
            should_cancel,
            cwd=cwd,
        )


_OLLAMA_DEFAULT_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")


def _resolve_ollama_url(credential_value: str | None) -> str:
    if credential_value and credential_value.strip():
        val = credential_value.strip()
        if not val.startswith("http"):
            val = f"http://{val}"
        return val.rstrip("/")
    return _OLLAMA_DEFAULT_URL.rstrip("/")


def _probe_ollama_api(credential_value: str | None) -> tuple[HealthCheckResult, list[str]]:
    base_url = _resolve_ollama_url(credential_value)
    detected_models: list[str] = []
    version_str = ""
    try:
        ver_resp = httpx.get(f"{base_url}/api/version", timeout=_PROBE_TIMEOUT_SECONDS)
        if ver_resp.status_code == 200:
            version_str = ver_resp.json().get("version", "")
    except Exception:
        pass

    try:
        tags_resp = httpx.get(f"{base_url}/api/tags", timeout=_PROBE_TIMEOUT_SECONDS)
        if tags_resp.status_code == 200:
            models_data = tags_resp.json().get("models", [])
            detected_models = [m.get("name", "") for m in models_data if m.get("name")]
            v_label = f"Ollama {version_str}".strip() if version_str else "Ollama"
            detail = f"Ollama reachable at {base_url} ({len(detected_models)} local model{'s' if len(detected_models) != 1 else ''}: {', '.join(detected_models[:5])})"
            return HealthCheckResult(connected=True, version=v_label, detail=detail), detected_models
    except Exception:
        pass

    cli_check = _detect_cli_version("ollama")
    if cli_check.connected:
        return (
            HealthCheckResult(
                connected=False,
                version=cli_check.version,
                detail=f"Detected 'ollama' on PATH, but server at {base_url} is not responding. Start Ollama with 'ollama serve'.",
            ),
            [],
        )

    return (
        HealthCheckResult(
            connected=False,
            detail=f"Ollama server not reachable at {base_url} and CLI not found.",
        ),
        [],
    )


def _apply_generated_files_to_worktree(cwd: str, text: str) -> list[str]:
    """Inspects text output for file modification blocks and writes them to the Git worktree."""
    import re
    applied = []
    pattern = re.compile(
        r'(?:###\s*FILE:|File:|```(?:[\w+-]+)?\s*filepath=)\s*([^\n\r]+)[\r\n]+```(?:[\w+-]+)?[\r\n](.*?)```',
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        rel_path = match.group(1).strip().strip('"`\'')
        content = match.group(2)
        if rel_path and not rel_path.startswith('/'):
            target_file = Path(cwd) / rel_path
            try:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(content, encoding='utf-8')
                applied.append(rel_path)
            except Exception:
                pass
    return applied


_REPO_CONTEXT_MAX_FILES_LISTED = 150
_REPO_CONTEXT_MAX_README_CHARS = 4000


def _build_repo_context(cwd: str) -> str:
    """A real, compact snapshot of the existing checkout -- a file listing
    plus the current README's actual content -- for a plain text-completion
    model that has no file-reading tool of its own (unlike the CLI-based
    adapters, which read the repo themselves). Without this, the model has
    nothing to go on but the instruction text and will honestly say it has
    no access to the codebase rather than inventing one."""
    root = Path(cwd)
    if not root.is_dir():
        return ""

    paths: list[str] = []
    for p in sorted(root.rglob("*")):
        if ".git" in p.parts:
            continue
        if p.is_file():
            paths.append(str(p.relative_to(root)))
        if len(paths) >= _REPO_CONTEXT_MAX_FILES_LISTED:
            break

    sections = [
        "### EXISTING REPOSITORY FILES\n" + ("\n".join(paths) if paths else "(empty repository)")
    ]

    for name in ("README.md", "Readme.md", "readme.md", "README"):
        readme = root / name
        if readme.is_file():
            try:
                content = readme.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            sections.append(
                f"### CURRENT CONTENTS OF {name}\n```\n{content[:_REPO_CONTEXT_MAX_README_CHARS]}\n```"
            )
            break

    return "\n\n".join(sections)


def _run_ollama_prompt_streaming(
    base_url: str,
    model: str,
    prompt: str,
    on_chunk,
    should_cancel,
    cwd: str | None = None,
) -> ExecutionResult:
    collected: list[str] = []
    usage: dict = {}
    target_model = model or "qwen3:14b"
    system_prompt = (
        "You are an expert AI software engineer. You are working in a Git repository.\n"
        "The existing repository files and README (if any) are included below -- this is "
        "the real, current state of the checkout, not a description of it. Use it; don't "
        "claim you lack access to the codebase.\n"
        "Analyze the user's instructions and generate code changes.\n"
        "When creating or updating files, format your edits as:\n"
        "### FILE: path/to/file\n"
        "```\n"
        "full file content\n"
        "```\n"
    )
    repo_context = _build_repo_context(cwd) if cwd else ""
    full_prompt = f"{system_prompt}\n\n{repo_context}\n\nTASK:\n{prompt}" if repo_context else f"{system_prompt}\n\nTASK:\n{prompt}"
    try:
        import json as _json
        with httpx.stream(
            "POST",
            f"{base_url}/api/generate",
            json={
                "model": target_model,
                "prompt": full_prompt,
                "stream": True,
            },
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        ) as resp:
            if resp.status_code != 200:
                resp.read()
                return ExecutionResult(
                    succeeded=False,
                    error=f"Ollama API returned HTTP {resp.status_code}: {resp.text[:400]}",
                )
            for line in resp.iter_lines():
                if should_cancel():
                    return ExecutionResult(
                        succeeded=False, output="".join(collected), error="Cancelled by user."
                    )
                if not line.strip():
                    continue
                try:
                    chunk_json = _json.loads(line)
                    text = chunk_json.get("response", "")
                    if text:
                        collected.append(text)
                        on_chunk(text)
                    if chunk_json.get("done", False):
                        # P6-3: Ollama's final streamed chunk genuinely
                        # includes these fields -- real counts/durations
                        # the server itself computed, not an estimate.
                        usage = {
                            k: chunk_json[k]
                            for k in (
                                "prompt_eval_count",
                                "eval_count",
                                "total_duration",
                                "load_duration",
                                "prompt_eval_duration",
                                "eval_duration",
                            )
                            if k in chunk_json
                        }
                        break
                except Exception:
                    continue
    except httpx.HTTPError as exc:
        return ExecutionResult(
            succeeded=False, output="".join(collected), error=f"Could not reach Ollama API: {exc}"
        )

    full_output = "".join(collected)
    if cwd and Path(cwd).exists():
        _apply_generated_files_to_worktree(cwd, full_output)

    return ExecutionResult(succeeded=True, output=full_output[:_MAX_OUTPUT_CHARS], usage=usage)


class OllamaAdapter(CodingAgentRuntimeAdapter):
    slug = "ollama"
    display_name = "Ollama"
    description = "Local model execution runtime via Ollama REST API / CLI"
    icon = "navigation/providers"
    supported_connection_modes = ("local_runtime", "custom_adapter")
    auth_method = "Local Ollama server (http://127.0.0.1:11434)"

    def capabilities(self) -> list[Capability]:
        return [
            Capability("Local inference", CapabilityState.VERIFIED),
            Capability("Worktree code editing", CapabilityState.VERIFIED),
            Capability("Model discovery", CapabilityState.VERIFIED),
        ]

    def supported_models(self) -> list[str]:
        # Discovers live models from Ollama or returns fallback
        try:
            _, models = _probe_ollama_api(None)
            if models:
                return models
        except Exception:
            pass
        return ["qwen3:14b", "qwen2.5-coder:14b", "deepseek-coder:6.7b", "codellama"]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        result, _ = _probe_ollama_api(credential_value)
        return result

    def start_execution(
        self, prompt: str, credential_value: str | None, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        base_url = _resolve_ollama_url(credential_value)
        collected: list[str] = []
        return _run_ollama_prompt_streaming(
            base_url,
            model or "qwen3:14b",
            prompt,
            lambda c: collected.append(c),
            lambda: False,
            cwd=cwd,
        )

    def start_execution_streaming(
        self, prompt, credential_value, on_chunk, should_cancel, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        base_url = _resolve_ollama_url(credential_value)
        return _run_ollama_prompt_streaming(
            base_url,
            model or "qwen3:14b",
            prompt,
            on_chunk,
            should_cancel,
            cwd=cwd,
        )


_SANDBOX_IMAGE = "python:3.11-slim"
_SANDBOX_MEMORY_LIMIT = "256m"
_SANDBOX_CPU_LIMIT = "0.5"


def _docker_daemon_status() -> HealthCheckResult:
    path = shutil.which("docker")
    if path is None:
        return HealthCheckResult(connected=False, detail="'docker' CLI not found on PATH.")
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return HealthCheckResult(connected=False, detail=f"Failed to execute 'docker': {exc}")
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        return HealthCheckResult(
            connected=False,
            detail=f"Docker daemon not reachable: {lines[0] if lines else 'unknown error'}",
        )
    version = (proc.stdout or "").strip()
    return HealthCheckResult(
        connected=True, version=version, detail=f"Docker daemon reachable (server {version})."
    )


def _sandboxed_cli_command(
    image: str,
    binary: str,
    prompt_flag: str,
    prompt: str,
    cwd: str | None = None,
    extra_args: list[str] | None = None,
    env: dict | None = None,
) -> list[str]:
    """Phase 2 (P2-3): like `_sandbox_command`, but for a coding-agent CLI
    that needs real network access to reach its own provider API -- only
    the filesystem is jailed (the task worktree is the one thing
    bind-mounted in) and memory/CPU are limited; network is deliberately
    NOT disabled here, unlike `_sandbox_command`'s fully offline
    docker_sandbox runtime. `image` must already have `binary` installed
    and on its PATH -- this function does not install anything."""
    cmd = ["docker", "run", "--rm", "--memory", _SANDBOX_MEMORY_LIMIT, "--cpus", _SANDBOX_CPU_LIMIT]
    if cwd:
        cmd += ["-v", f"{cwd}:/workspace", "-w", "/workspace"]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [image, binary, prompt_flag, prompt, *(extra_args or [])]
    return cmd


def _run_cli_prompt_sandboxed(
    image: str,
    binary: str,
    prompt_flag: str,
    prompt: str,
    cwd: str | None = None,
    extra_args: list[str] | None = None,
    env: dict | None = None,
) -> ExecutionResult:
    health = _docker_daemon_status()
    if not health.connected:
        return ExecutionResult(
            succeeded=False,
            error=f"Sandboxed execution requested for '{binary}' but Docker is unavailable: {health.detail}",
        )
    try:
        proc = subprocess.run(
            _sandboxed_cli_command(image, binary, prompt_flag, prompt, cwd, extra_args, env),
            capture_output=True,
            text=True,
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ExecutionResult(succeeded=False, error=f"Failed to run sandboxed '{binary}': {exc}")
    if proc.returncode != 0:
        return ExecutionResult(
            succeeded=False,
            error=(proc.stderr or proc.stdout or f"Sandboxed '{binary}' exited with code {proc.returncode}")[
                :_MAX_OUTPUT_CHARS
            ],
        )
    return ExecutionResult(succeeded=True, output=(proc.stdout or "")[:_MAX_OUTPUT_CHARS])


def _run_cli_prompt_streaming_sandboxed(
    image: str,
    binary: str,
    prompt_flag: str,
    prompt: str,
    on_chunk,
    should_cancel,
    cwd: str | None = None,
    extra_args: list[str] | None = None,
    env: dict | None = None,
) -> ExecutionResult:
    """Streaming counterpart of `_run_cli_prompt_sandboxed`, mirroring
    `_run_cli_prompt_streaming`'s real line-by-line read and real
    cancellation (terminates the `docker run` client, which Docker
    forwards to the container) but inside the sandboxed container."""
    health = _docker_daemon_status()
    if not health.connected:
        return ExecutionResult(
            succeeded=False,
            error=f"Sandboxed execution requested for '{binary}' but Docker is unavailable: {health.detail}",
        )
    try:
        proc = subprocess.Popen(
            _sandboxed_cli_command(image, binary, prompt_flag, prompt, cwd, extra_args, env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return ExecutionResult(succeeded=False, error=f"Failed to run sandboxed '{binary}': {exc}")

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
    proc.wait(timeout=_EXECUTION_TIMEOUT_SECONDS if cancelled else None)

    output = "".join(collected)[:_MAX_OUTPUT_CHARS]
    if cancelled:
        return ExecutionResult(succeeded=False, output=output, error="Cancelled by user.")
    if proc.returncode != 0:
        return ExecutionResult(
            succeeded=False,
            output=output,
            error=output or f"Sandboxed '{binary}' exited with code {proc.returncode}",
        )
    return ExecutionResult(succeeded=True, output=output)


def _sandbox_command(prompt: str, cwd: str | None = None) -> list[str]:
    # --network none: no network access at all from inside the container.
    # --memory/--cpus: real resource limits enforced by the Docker daemon,
    # not just documentation. --rm: the container is destroyed on exit, so
    # nothing persists between runs. When `cwd` is a real Git worktree
    # (Phase 14), it's bind-mounted in so the container's real filesystem
    # edits land directly in that checkout rather than being thrown away.
    cmd = ["docker", "run", "--rm", "--network", "none", "--memory", _SANDBOX_MEMORY_LIMIT, "--cpus", _SANDBOX_CPU_LIMIT]
    if cwd:
        cmd += ["-v", f"{cwd}:/workspace", "-w", "/workspace"]
    cmd += [_SANDBOX_IMAGE, "sh", "-c", prompt]
    return cmd


def _run_docker_sandbox(prompt: str, cwd: str | None = None) -> ExecutionResult:
    health = _docker_daemon_status()
    if not health.connected:
        return ExecutionResult(succeeded=False, error=health.detail)
    try:
        proc = subprocess.run(
            _sandbox_command(prompt, cwd),
            capture_output=True,
            text=True,
            timeout=_EXECUTION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ExecutionResult(succeeded=False, error=f"Failed to run sandbox container: {exc}")
    if proc.returncode != 0:
        return ExecutionResult(
            succeeded=False,
            error=(proc.stderr or proc.stdout or f"Sandbox container exited with code {proc.returncode}")[
                :_MAX_OUTPUT_CHARS
            ],
        )
    return ExecutionResult(succeeded=True, output=(proc.stdout or "")[:_MAX_OUTPUT_CHARS])


def _run_docker_sandbox_streaming(prompt: str, on_chunk, should_cancel, cwd: str | None = None) -> ExecutionResult:
    """Like `_run_docker_sandbox`, but reads the real container's stdout
    line by line and can terminate the `docker run` client early on real
    cancellation -- which Docker forwards to the container itself.
    """
    health = _docker_daemon_status()
    if not health.connected:
        return ExecutionResult(succeeded=False, error=health.detail)
    try:
        proc = subprocess.Popen(
            _sandbox_command(prompt, cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return ExecutionResult(succeeded=False, error=f"Failed to run sandbox container: {exc}")

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
    proc.wait(timeout=_EXECUTION_TIMEOUT_SECONDS if cancelled else None)

    output = "".join(collected)[:_MAX_OUTPUT_CHARS]
    if cancelled:
        return ExecutionResult(succeeded=False, output=output, error="Cancelled by user.")
    if proc.returncode != 0:
        return ExecutionResult(
            succeeded=False,
            output=output,
            error=output or f"Sandbox container exited with code {proc.returncode}",
        )
    return ExecutionResult(succeeded=True, output=output)


class DockerSandboxAdapter(CodingAgentRuntimeAdapter):
    """Runs a task's prompt as a shell command inside an isolated,
    network-disabled, resource-limited container rather than directly on
    the backend host -- for safely executing arbitrary scripts, not for
    talking to a hosted coding-agent provider. Needs no credential: the
    only real dependency is a reachable local Docker daemon.
    """

    slug = "docker_sandbox"
    display_name = "Docker Sandbox"
    description = "Executes the task prompt as a shell command inside an isolated container (no network, memory/CPU limits)"
    icon = "navigation/providers"
    supported_connection_modes = ("local_runtime",)
    auth_method = "Local Docker daemon (no credential needed)"

    def capabilities(self) -> list[Capability]:
        return [
            Capability("Network-isolated execution", CapabilityState.TESTED),
            Capability("Memory/CPU-limited execution", CapabilityState.TESTED),
            Capability("Docker daemon detection", CapabilityState.VERIFIED),
        ]

    def supported_models(self) -> list[str]:
        return ["sandbox-bash"]

    def health_check(self, credential_value: str | None) -> HealthCheckResult:
        return _docker_daemon_status()

    def start_execution(
        self, prompt: str, credential_value: str | None, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        return _run_docker_sandbox(prompt, cwd)

    def start_execution_streaming(
        self, prompt, credential_value, on_chunk, should_cancel, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        return _run_docker_sandbox_streaming(prompt, on_chunk, should_cancel, cwd)


class CustomAdapter(CodingAgentRuntimeAdapter):
    slug = "custom"
    display_name = "Custom Agent"
    description = "Adapter implementing the common Agent Runtime Interface"
    icon = "navigation/providers"
    supported_connection_modes = ("custom_adapter",)
    auth_method = "Configured credential"

    def capabilities(self) -> list[Capability]:
        return [Capability("Depends on adapter", CapabilityState.DECLARED)]

    def supported_models(self) -> list[str]:
        return ["custom-agent"]

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

    def start_execution(
        self, prompt: str, credential_value: str | None, cwd: str | None = None, model: str | None = None
    ) -> ExecutionResult:
        # `cwd` (a local Git worktree) is honestly ignored here: this adapter
        # calls a remote HTTP endpoint with no access to this host's
        # filesystem, so there is nothing real it could do with it.
        if not credential_value:
            return ExecutionResult(succeeded=False, error="No endpoint configured for this custom adapter.")
        try:
            resp = httpx.post(
                credential_value,
                json={"prompt": prompt, "model": model},
                timeout=_EXECUTION_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            return ExecutionResult(succeeded=False, error=f"Could not reach endpoint: {exc}")
        if resp.status_code >= 400:
            return ExecutionResult(succeeded=False, error=f"Endpoint returned HTTP {resp.status_code}.")
        return ExecutionResult(succeeded=True, output=resp.text[:_MAX_OUTPUT_CHARS])
