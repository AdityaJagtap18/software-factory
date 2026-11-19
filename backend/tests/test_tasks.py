import json
import time

from app.services.agent_runtime.adapters import ClaudeCodeAdapter
from app.services.agent_runtime.base import ExecutionResult, HealthCheckResult


def _wait_for_terminal_status(client, project_id, task_id, headers, timeout=10):
    """Task execution now runs in a background thread (Phase 4), so `start`
    returns immediately with status "running" — poll the real task row
    until the background run actually finishes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/projects/{project_id}/tasks/{task_id}", headers=headers).json()
        if body["status"] != "running":
            return body
        time.sleep(0.1)
    raise AssertionError("task did not reach a terminal status in time")


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


def test_create_and_list_tasks(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Fix login bug", "description": "NPE on empty password"},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "not_started"
    assert body["priority"] == "medium"

    r2 = client.get(f"/api/v1/projects/{project['id']}/tasks", headers=alice)
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_viewer_cannot_create_task(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org, project = _project(client, alice)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=alice,
    )
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "bob@example.com", "role": "viewer"},
        headers=alice,
    )

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "x"}, headers=bob
    )
    assert r.status_code == 403


def test_starting_task_with_no_connection_fails_honestly(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Do thing"}, headers=alice
    ).json()

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "failed"
    assert "no coding-agent connection" in body["error_message"].lower()


def test_starting_task_on_this_machine_fails_honestly_without_mocking(client):
    """No claude/codex/gemini CLI is installed here and no API key is
    configured, so starting a task against a real (non-mocked) local-runtime
    connection must fail with the real reason — never a simulated success."""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Do thing", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "failed"
    assert body["output"] == ""
    assert "not connected" in body["error_message"].lower()
    assert body["started_at"] is not None
    assert body["completed_at"] is not None


def test_connection_from_another_org_is_rejected(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    _org_a, project_a = _project(client, alice, "Acme")
    org_b = client.post("/api/v1/organizations", json={"name": "Globex"}, headers=bob).json()
    other_connection = client.post(
        f"/api/v1/organizations/{org_b['id']}/coding-agent-connections",
        json={"runtime_slug": "codex", "connection_mode": "local_runtime"},
        headers=bob,
    ).json()

    r = client.post(
        f"/api/v1/projects/{project_a['id']}/tasks",
        json={"title": "x", "coding_agent_connection_id": other_connection["id"]},
        headers=alice,
    )
    assert r.status_code == 400


def test_successful_execution_marks_task_completed_with_real_output(client, monkeypatch):
    """Stub only the adapter's execution edge (a real subprocess/network call
    would be non-hermetic); verify the task pipeline honestly records a
    completed status and the adapter's actual output, never fabricated data."""
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )
    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel):
        on_chunk(f"echo: {prompt}")
        return ExecutionResult(succeeded=True, output=f"echo: {prompt}")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={
            "title": "Write a haiku",
            "description": "Write a haiku about testing",
            "coding_agent_connection_id": connection["id"],
        },
        headers=alice,
    ).json()

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "completed"
    assert body["output"] == "echo: Write a haiku about testing"
    assert body["error_message"] == ""


def test_cannot_start_task_already_running(client, monkeypatch):
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=False, detail="still down"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "x"}, headers=alice
    ).json()

    import uuid

    from app.core.database import SessionLocal
    from app.models.task import Task, TaskStatus

    db = SessionLocal()
    db_task = db.get(Task, uuid.UUID(task["id"]))
    db_task.status = TaskStatus.RUNNING
    db.commit()
    db.close()

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    assert r.status_code == 409


def test_cancel_requires_running_task(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "x"}, headers=alice
    ).json()

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/cancel", headers=alice)
    assert r.status_code == 409


def test_cancelling_a_running_task_stops_it_with_partial_output(client, monkeypatch):
    """Simulate a slow adapter that checks `should_cancel` between chunks, as
    the real CLI/SSE streaming implementations do. Cancelling mid-run must
    produce the real partial output collected so far, not a fabricated one."""
    import threading

    started = threading.Event()

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel):
        on_chunk("chunk-1 ")
        started.set()
        for i in range(2, 50):
            if should_cancel():
                return ExecutionResult(succeeded=False, output="chunk-1 ", error="Cancelled by user.")
            time.sleep(0.05)
        return ExecutionResult(succeeded=True, output="finished without cancellation")

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )
    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Long task", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()

    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    started.wait(timeout=5)

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/cancel", headers=alice)
    assert r.status_code == 200

    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "failed"
    assert body["error_message"] == "Cancelled by user."
    assert body["output"] == "chunk-1 "


def test_stream_endpoint_emits_sse_events_until_terminal(client, monkeypatch):
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=False, detail="still down"),
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "x", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)

    url = f"/api/v1/projects/{project['id']}/tasks/{task['id']}/stream"
    events = []
    with client.stream("GET", url, headers=alice) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
            if events and events[-1]["status"] != "running":
                break

    assert events[-1]["status"] == "failed"
    assert "not connected" in events[-1]["error_message"].lower()
