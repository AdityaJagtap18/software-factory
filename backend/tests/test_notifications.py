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


def test_a_completed_task_notifies_its_creator_with_a_real_delivered_notification(client, monkeypatch):
    """P6-1: a real event (a task the user created actually finishing)
    produces a real, durable `Notification` row for that user -- not a
    simulated feed. Checked via the real read endpoint, not the live
    WebSocket (which `test_notification_websocket...` below covers
    separately)."""
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
            succeeded=True, output="All done"
        ),
    )

    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Fix the bug", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "completed"

    before = client.get("/api/v1/notifications/unread-count", headers=alice).json()
    assert before["count"] >= 1

    listed = client.get("/api/v1/notifications", headers=alice).json()
    matches = [n for n in listed if n["type"] == "task_completed" and task["title"] in n["title"]]
    assert len(matches) == 1
    notification = matches[0]
    assert notification["read_at"] is None

    r = client.post(f"/api/v1/notifications/{notification['id']}/read", headers=alice)
    assert r.status_code == 200, r.text
    assert r.json()["read_at"] is not None

    after = client.get("/api/v1/notifications/unread-count", headers=alice).json()
    assert after["count"] == before["count"] - 1


def test_a_failed_task_notifies_its_creator_with_the_real_error(client, monkeypatch):
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
            succeeded=False, error="the CLI crashed"
        ),
    )

    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Flaky task", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "failed"

    listed = client.get("/api/v1/notifications", headers=alice).json()
    matches = [n for n in listed if n["type"] == "task_failed"]
    assert len(matches) == 1
    assert "the CLI crashed" in matches[0]["body"]


def test_a_user_cannot_mark_someone_elses_notification_read(client, monkeypatch):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
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
        json={"title": "Alice's task", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    _wait_for_terminal_status(client, project["id"], task["id"], alice)

    notification = client.get("/api/v1/notifications", headers=alice).json()[0]
    r = client.post(f"/api/v1/notifications/{notification['id']}/read", headers=bob)
    assert r.status_code == 404
