"""Phase 2 (P2-3): sandboxed local-CLI execution plumbing.

No real per-CLI image (one with Claude Code/Codex/Gemini CLI/Qwen actually
installed) has been built yet -- so these tests prove two separate, real
things instead of pretending a sandboxed Claude Code run works end to end:

1. The command this plumbing builds is correct (pure, no Docker needed).
2. The underlying sandboxed-execution mechanism genuinely works against a
   real Docker daemon -- using the `python:3.11-slim` image already used
   (and already verified reachable) by `DockerSandboxAdapter`, standing in
   for "a CLI image," so this test doesn't depend on a real coding-agent
   CLI's own Docker image existing.
"""

import pytest

from app.services.agent_runtime.adapters import (
    DockerSandboxAdapter,
    _run_cli_prompt_streaming_sandboxed,
    _sandboxed_cli_command,
)

_STAND_IN_IMAGE = "python:3.11-slim"


def _docker_available() -> bool:
    return DockerSandboxAdapter().health_check(None).connected


requires_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker daemon is not reachable in this environment"
)


def test_sandboxed_command_mounts_worktree_and_limits_resources(tmp_path):
    cmd = _sandboxed_cli_command(
        "claude-code-sandbox:latest",
        "claude",
        "-p",
        "fix the bug",
        cwd=str(tmp_path),
        extra_args=["--permission-mode", "acceptEdits"],
        env={"ANTHROPIC_API_KEY": "sk-test"},
    )
    assert cmd[0:3] == ["docker", "run", "--rm"]
    assert "--memory" in cmd and "--cpus" in cmd
    # Deliberately NOT network-disabled -- these CLIs must reach their
    # own provider API, unlike the fully offline docker_sandbox runtime.
    assert "--network" not in cmd
    assert f"{tmp_path}:/workspace" in cmd
    assert "-w" in cmd and "/workspace" in cmd
    assert "-e" in cmd and "ANTHROPIC_API_KEY=sk-test" in cmd
    assert "claude-code-sandbox:latest" in cmd
    tail = cmd[cmd.index("claude-code-sandbox:latest") + 1 :]
    assert tail == ["claude", "-p", "fix the bug", "--permission-mode", "acceptEdits"]


def test_sandboxed_command_without_cwd_has_no_volume_mount():
    cmd = _sandboxed_cli_command("some-image:latest", "codex", "exec", "do work")
    assert "-v" not in cmd
    assert "-w" not in cmd


@requires_docker
def test_sandboxed_execution_actually_runs_in_a_real_container_with_network(tmp_path):
    """Proves the mechanism end to end: real container, real worktree
    bind-mount, real streamed output, and -- the key difference from
    `docker_sandbox` -- real network reachability (DNS resolution
    succeeds), since these CLIs must be able to call their own provider
    API."""
    (tmp_path / "marker.txt").write_text("hello from the real worktree\n")

    chunks: list[str] = []
    result = _run_cli_prompt_streaming_sandboxed(
        _STAND_IN_IMAGE,
        "python3",
        "-c",
        "import socket; print(open('marker.txt').read().strip()); "
        "print('DNS_OK' if socket.gethostbyname('github.com') else 'DNS_FAIL')",
        on_chunk=chunks.append,
        should_cancel=lambda: False,
        cwd=str(tmp_path),
    )
    assert result.succeeded, result.error
    assert "hello from the real worktree" in result.output
    assert "DNS_OK" in result.output


def test_claude_code_adapter_routes_through_sandbox_only_when_configured(monkeypatch):
    """Proves the wiring, not just the low-level helper: with no sandbox
    image configured (the honest default today), the adapter must take
    its original, unsandboxed path -- never silently switch behavior."""
    from app.services.agent_runtime import adapters as adapters_module
    from app.services.agent_runtime.adapters import ClaudeCodeAdapter

    calls = {"direct": 0, "sandboxed": 0}
    monkeypatch.setattr(
        adapters_module,
        "_run_cli_prompt_streaming",
        lambda *a, **k: calls.__setitem__("direct", calls["direct"] + 1)
        or adapters_module.ExecutionResult(succeeded=True, output="direct"),
    )
    monkeypatch.setattr(
        adapters_module,
        "_run_cli_prompt_streaming_sandboxed",
        lambda *a, **k: calls.__setitem__("sandboxed", calls["sandboxed"] + 1)
        or adapters_module.ExecutionResult(succeeded=True, output="sandboxed"),
    )

    class _NoSandbox:
        claude_code_sandbox_image = ""

    monkeypatch.setattr(adapters_module, "get_settings", lambda: _NoSandbox())
    adapter = ClaudeCodeAdapter()
    result = adapter.start_execution_streaming("do work", None, lambda c: None, lambda: False)
    assert result.output == "direct"
    assert calls == {"direct": 1, "sandboxed": 0}

    class _WithSandbox:
        claude_code_sandbox_image = "claude-code-sandbox:latest"

    monkeypatch.setattr(adapters_module, "get_settings", lambda: _WithSandbox())
    result = adapter.start_execution_streaming("do work", None, lambda c: None, lambda: False)
    assert result.output == "sandboxed"
    assert calls == {"direct": 1, "sandboxed": 1}


@requires_docker
def test_sandboxed_execution_can_be_cancelled(tmp_path):
    chunks: list[str] = []
    cancel_after_first_chunk = {"flag": False}

    def should_cancel() -> bool:
        return cancel_after_first_chunk["flag"]

    def on_chunk(line: str) -> None:
        chunks.append(line)
        cancel_after_first_chunk["flag"] = True

    result = _run_cli_prompt_streaming_sandboxed(
        _STAND_IN_IMAGE,
        "python3",
        "-c",
        "import time\nfor i in range(20):\n    print(i, flush=True)\n    time.sleep(0.5)\n",
        on_chunk=on_chunk,
        should_cancel=should_cancel,
        cwd=str(tmp_path),
    )
    assert not result.succeeded
    assert result.error == "Cancelled by user."
    assert len(chunks) < 20
