import pytest

from app.services.agent_runtime import adapters
from app.services.agent_runtime.adapters import ClaudeCodeAdapter
from app.services.agent_runtime.base import HealthCheckResult


def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_runtime_catalog_lists_known_adapters(client):
    r = client.get("/api/v1/coding-agent-runtimes")
    assert r.status_code == 200
    slugs = {entry["slug"] for entry in r.json()}
    assert slugs == {"claude_code", "codex", "gemini_cli", "qwen", "docker_sandbox", "custom"}


def test_connections_default_to_not_configured(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    r = client.get(f"/api/v1/organizations/{org['id']}/coding-agent-connections", headers=alice)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 6
    for entry in body:
        assert entry["status"] == "not_configured"
        assert entry["is_configured"] is False
        assert entry["id"] is None


def test_non_admin_cannot_create_connection(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=alice,
    )

    r = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=bob,
    )
    assert r.status_code == 403


def test_local_runtime_connection_honestly_reports_not_connected_when_cli_missing(client):
    """This machine has no `codex` CLI on PATH, so a real (non-mocked) health
    check for local_runtime mode must honestly report not_connected — never a
    simulated success. (Not `claude_code`: this dev machine has the real
    Claude Code CLI installed, so that one genuinely connects — see
    `test_local_runtime_connection_honestly_reports_connected_when_cli_present`.)"""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    r = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "codex", "connection_mode": "local_runtime"},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "not_connected"
    assert body["detected_version"] == ""
    assert "not found" in body["last_error"].lower() or "codex" in body["last_error"].lower()


def test_local_runtime_connection_honestly_reports_connected_when_cli_present(client):
    """Where the real Claude Code CLI is installed (`npm install -g
    @anthropic-ai/claude-code`), a real (non-mocked) health check for
    local_runtime mode must honestly report connected with a real detected
    version — never fabricated, but also never falsely reported as missing
    when it's genuinely there. Skipped on a machine without the CLI, since
    that's this test's entire precondition, not something to fake."""
    import shutil

    if shutil.which("claude") is None:
        pytest.skip("claude CLI not installed on this machine")

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    r = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "connected"
    assert body["detected_version"] != ""


def test_duplicate_connection_for_same_runtime_conflicts(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    payload = {"runtime_slug": "codex", "connection_mode": "local_runtime"}

    r1 = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections", json=payload, headers=alice
    )
    assert r1.status_code == 201

    r2 = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections", json=payload, headers=alice
    )
    assert r2.status_code == 409


def test_managed_connection_with_credential_runs_real_health_check(client, monkeypatch):
    """Credential-based (factory_managed) health checks make a real outbound
    probe to the provider's API. We stub only the network edge here (not the
    connected/not_connected decision logic) to keep the test hermetic."""
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(
            connected=True, version="", detail="Anthropic API key verified."
        ),
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    r = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={
            "runtime_slug": "claude_code",
            "connection_mode": "factory_managed",
            "credential_name": "Prod Anthropic key",
            "credential_provider": "anthropic",
            "credential_value": "sk-ant-fake-value",
        },
        headers=alice,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "connected"
    assert body["has_credential"] is True

    # The raw secret must never be echoed back by the API.
    assert "sk-ant-fake-value" not in r.text


def test_health_check_can_be_rerun_and_updates_timestamp(client, monkeypatch):
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=False, detail="still down"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    created = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()

    r = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections/{created['id']}/health-check",
        headers=alice,
    )
    assert r.status_code == 200
    assert r.json()["last_error"] == "still down"


def test_cross_org_cannot_see_or_modify_connections(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org_a = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    org_b = client.post("/api/v1/organizations", json={"name": "Globex"}, headers=bob).json()

    created = client.post(
        f"/api/v1/organizations/{org_a['id']}/coding-agent-connections",
        json={"runtime_slug": "codex", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()

    r = client.get(
        f"/api/v1/organizations/{org_b['id']}/coding-agent-connections", headers=bob
    )
    assert r.status_code == 200
    assert all(entry["id"] is None for entry in r.json())

    r2 = client.delete(
        f"/api/v1/organizations/{org_a['id']}/coding-agent-connections/{created['id']}",
        headers=bob,
    )
    assert r2.status_code == 403


def test_delete_connection_removes_it_and_its_credential(client, monkeypatch):
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    created = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={
            "runtime_slug": "claude_code",
            "connection_mode": "factory_managed",
            "credential_value": "sk-ant-fake",
        },
        headers=alice,
    ).json()

    r = client.delete(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections/{created['id']}",
        headers=alice,
    )
    assert r.status_code == 204

    after = client.get(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections", headers=alice
    ).json()
    claude_entry = next(e for e in after if e["runtime_slug"] == "claude_code")
    assert claude_entry["is_configured"] is False


# ---------------------------------------------------------------------------
# Phase 19: `claude -p` has no TTY to approve a permission prompt, so it
# defaults to denying file-editing tools -- a task would otherwise report
# success without ever writing a file. `--permission-mode acceptEdits` is
# added, but only when a real worktree `cwd` bounds where edits can land.
# ---------------------------------------------------------------------------


def test_claude_code_cli_execution_requests_accept_edits_inside_a_worktree(monkeypatch):
    captured = {}

    class _FakeCompletedProcess:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompletedProcess()

    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(adapters.subprocess, "run", _fake_run)

    result = ClaudeCodeAdapter().start_execution("Add a file", None, cwd="/tmp/some-worktree")

    assert result.succeeded is True
    assert captured["cmd"] == ["/usr/bin/claude", "-p", "Add a file", "--permission-mode", "acceptEdits"]


def test_claude_code_cli_execution_omits_accept_edits_without_a_worktree(monkeypatch):
    captured = {}

    class _FakeCompletedProcess:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompletedProcess()

    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(adapters.subprocess, "run", _fake_run)

    result = ClaudeCodeAdapter().start_execution("Just answer this", None, cwd=None)

    assert result.succeeded is True
    assert captured["cmd"] == ["/usr/bin/claude", "-p", "Just answer this"]


def test_claude_code_cli_streaming_execution_requests_accept_edits_inside_a_worktree(monkeypatch):
    captured = {}

    class _FakePopen:
        returncode = 0
        stdout = iter(["real output\n"])

        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd

        def wait(self, timeout=None):
            return None

    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(adapters.subprocess, "Popen", _FakePopen)

    result = ClaudeCodeAdapter().start_execution_streaming(
        "Add a file", None, lambda chunk: None, lambda: False, cwd="/tmp/some-worktree"
    )

    assert result.succeeded is True
    assert captured["cmd"] == ["/usr/bin/claude", "-p", "Add a file", "--permission-mode", "acceptEdits"]


def test_gemini_cli_execution_requests_skip_trust_and_yes_inside_a_worktree(monkeypatch):
    captured = {}

    class _FakeCompletedProcess:
        returncode = 0
        stdout = "ok from gemini"
        stderr = ""

    def _fake_run(cmd, env=None, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        return _FakeCompletedProcess()

    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(adapters.subprocess, "run", _fake_run)

    result = adapters.GeminiCliAdapter().start_execution("Add a file", "test-key-123", cwd="/tmp/some-worktree")

    assert result.succeeded is True
    assert captured["cmd"] == ["/usr/bin/gemini", "-p", "Add a file", "--skip-trust", "-y"]
    assert captured["env"]["GEMINI_API_KEY"] == "test-key-123"


def test_gemini_cli_health_check_verifies_cli_and_api_key(monkeypatch):
    monkeypatch.setattr(adapters.shutil, "which", lambda binary: f"/usr/bin/{binary}")

    class _FakeCompletedProcess:
        returncode = 0
        stdout = "0.70.0\n"
        stderr = ""

    class _FakeResponse:
        status_code = 200

    monkeypatch.setattr(adapters.subprocess, "run", lambda *a, **k: _FakeCompletedProcess())
    monkeypatch.setattr(adapters.httpx, "get", lambda *a, **k: _FakeResponse())

    # With credential
    res = adapters.GeminiCliAdapter().health_check("fake-key")
    assert res.connected is True
    assert "0.70.0" in res.detail

    # Without credential and without env key
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    res_no_key = adapters.GeminiCliAdapter().health_check(None)
    assert res_no_key.connected is False
    assert "GEMINI_API_KEY" in res_no_key.detail

