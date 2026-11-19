from app.services.agent_runtime.adapters import ClaudeCodeAdapter
from app.services.agent_runtime.base import ExecutionResult, HealthCheckResult


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
    body = r.json()
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
    body = r.json()
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
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "start_execution",
        lambda self, prompt, credential_value: ExecutionResult(succeeded=True, output=f"echo: {prompt}"),
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
        json={
            "title": "Write a haiku",
            "description": "Write a haiku about testing",
            "coding_agent_connection_id": connection["id"],
        },
        headers=alice,
    ).json()

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    assert r.status_code == 200
    body = r.json()
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
