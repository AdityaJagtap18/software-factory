from app.services.agent_runtime.adapters import ClaudeCodeAdapter
from app.services.agent_runtime.base import ExecutionResult, HealthCheckResult
from tests.test_tasks import _wait_for_terminal_status


def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _project(client, headers, name="Acme"):
    org = client.post("/api/v1/organizations", json={"name": name}, headers=headers).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=headers
    ).json()
    return org, project


def test_real_adapter_usage_is_recorded_on_the_execution_attempt(client, monkeypatch):
    """P6-3: when the adapter's own result genuinely reports usage (here
    simulated at the adapter boundary the way Ollama's real API actually
    would), it lands on the real `TaskExecutionAttempt` row -- readable via
    the existing `/attempts` endpoint, never fabricated when absent."""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "start_execution_streaming",
        lambda self, prompt, credential_value, on_chunk, should_cancel, cwd=None: ExecutionResult(
            succeeded=True, output="done", usage={"prompt_eval_count": 42, "eval_count": 17}
        ),
    )

    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Measure usage", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    _wait_for_terminal_status(client, project["id"], task["id"], alice)

    attempts = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/attempts", headers=alice
    ).json()
    assert len(attempts) == 1
    assert attempts[0]["usage"] == {"prompt_eval_count": 42, "eval_count": 17}


def test_adapter_with_no_usage_data_reports_an_empty_dict_not_a_fabricated_estimate(client, monkeypatch):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "start_execution_streaming",
        lambda self, prompt, credential_value, on_chunk, should_cancel, cwd=None: ExecutionResult(
            succeeded=True, output="done"
        ),
    )

    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "No usage data", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    _wait_for_terminal_status(client, project["id"], task["id"], alice)

    attempts = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/attempts", headers=alice
    ).json()
    assert attempts[0]["usage"] == {}


def test_real_execution_spans_are_recorded_for_the_attempt(client, monkeypatch):
    """P6-3: a structured trace -- every span is a real, timed phase this
    backend actually ran through for this attempt."""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "start_execution_streaming",
        lambda self, prompt, credential_value, on_chunk, should_cancel, cwd=None: ExecutionResult(
            succeeded=True, output="done"
        ),
    )

    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Trace this", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    _wait_for_terminal_status(client, project["id"], task["id"], alice)

    spans = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/spans", headers=alice
    ).json()
    names = [s["name"] for s in spans]
    assert "adapter_execution" in names
    adapter_span = next(s for s in spans if s["name"] == "adapter_execution")
    assert adapter_span["succeeded"] is True
    assert adapter_span["completed_at"] is not None
