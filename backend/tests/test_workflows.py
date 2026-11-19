import json
import time

from app.services.agent_runtime.adapters import ClaudeCodeAdapter
from app.services.agent_runtime.base import ExecutionResult, HealthCheckResult


def _wait_for_terminal_workflow_status(client, project_id, workflow_id, headers, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(
            f"/api/v1/projects/{project_id}/workflows/{workflow_id}", headers=headers
        ).json()
        if body["status"] != "running":
            return body
        time.sleep(0.1)
    raise AssertionError("workflow did not reach a terminal status in time")


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


def test_create_and_list_workflows(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "Ship feature X",
            "description": "Plan, implement, review",
            "steps": [{"title": "Plan"}, {"title": "Implement"}, {"title": "Review"}],
        },
        headers=alice,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "not_started"
    assert len(body["steps"]) == 3
    assert [s["title"] for s in body["steps"]] == ["Plan", "Implement", "Review"]

    r2 = client.get(f"/api/v1/projects/{project['id']}/workflows", headers=alice)
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_workflow_requires_at_least_one_step(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={"name": "Empty", "steps": []},
        headers=alice,
    )
    assert r.status_code == 422


def test_viewer_cannot_create_workflow(client):
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
        f"/api/v1/projects/{project['id']}/workflows",
        json={"name": "x", "steps": [{"title": "a"}]},
        headers=bob,
    )
    assert r.status_code == 403


def test_workflow_step_on_this_machine_fails_honestly_without_mocking(client):
    """No claude/codex/gemini CLI is installed here and no API key is
    configured, so a workflow step against a real (non-mocked)
    local-runtime connection must fail with the real reason, and the
    workflow must stop there — never a fabricated success."""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "Real failure",
            "steps": [
                {"title": "Step one", "coding_agent_connection_id": connection["id"]},
                {"title": "Step two", "coding_agent_connection_id": connection["id"]},
            ],
        },
        headers=alice,
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice
    )
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    body = _wait_for_terminal_workflow_status(client, project["id"], workflow["id"], alice)
    assert body["status"] == "failed"
    assert body["steps"][0]["status"] == "failed"
    assert "not connected" in body["steps"][0]["error_message"].lower()
    # The second step must never have been started once the first genuinely failed.
    assert body["steps"][1]["status"] == "not_started"


def test_multi_step_workflow_succeeds_when_every_step_succeeds(client, monkeypatch):
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel):
        on_chunk(f"done: {prompt}")
        return ExecutionResult(succeeded=True, output=f"done: {prompt}")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "All green",
            "steps": [
                {"title": "Step one", "coding_agent_connection_id": connection["id"]},
                {"title": "Step two", "coding_agent_connection_id": connection["id"]},
            ],
        },
        headers=alice,
    ).json()

    client.post(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice)

    body = _wait_for_terminal_workflow_status(client, project["id"], workflow["id"], alice)
    assert body["status"] == "completed"
    assert body["steps"][0]["status"] == "completed"
    assert body["steps"][1]["status"] == "completed"
    assert body["steps"][0]["output"] == "done: Step one"
    assert body["steps"][1]["output"] == "done: Step two"


def test_second_step_never_runs_when_first_step_fails(client, monkeypatch):
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel):
        return ExecutionResult(succeeded=False, output="", error="Simulated real failure")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "Fails at step one",
            "steps": [
                {"title": "Step one", "coding_agent_connection_id": connection["id"]},
                {"title": "Step two", "coding_agent_connection_id": connection["id"]},
            ],
        },
        headers=alice,
    ).json()

    client.post(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice)

    body = _wait_for_terminal_workflow_status(client, project["id"], workflow["id"], alice)
    assert body["status"] == "failed"
    assert body["steps"][0]["status"] == "failed"
    assert body["steps"][0]["error_message"] == "Simulated real failure"
    assert body["steps"][1]["status"] == "not_started"


def test_cancel_requires_running_workflow(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={"name": "x", "steps": [{"title": "a"}]},
        headers=alice,
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/cancel", headers=alice
    )
    assert r.status_code == 409


def test_cancelling_a_running_workflow_stops_the_current_step(client, monkeypatch):
    import threading

    started = threading.Event()

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel):
        on_chunk("chunk-1 ")
        started.set()
        for _ in range(50):
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
    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "Long running",
            "steps": [
                {"title": "Step one", "coding_agent_connection_id": connection["id"]},
                {"title": "Step two", "coding_agent_connection_id": connection["id"]},
            ],
        },
        headers=alice,
    ).json()

    client.post(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice)
    started.wait(timeout=5)

    r = client.post(
        f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/cancel", headers=alice
    )
    assert r.status_code == 200

    body = _wait_for_terminal_workflow_status(client, project["id"], workflow["id"], alice)
    assert body["status"] == "failed"
    assert body["steps"][0]["status"] == "failed"
    assert body["steps"][0]["error_message"] == "Cancelled by user."
    assert body["steps"][0]["output"] == "chunk-1 "
    assert body["steps"][1]["status"] == "not_started"


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
    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={"name": "x", "steps": [{"title": "a", "coding_agent_connection_id": connection["id"]}]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice)

    url = f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/stream"
    events = []
    with client.stream("GET", url, headers=alice) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
            if events and events[-1]["status"] != "running":
                break

    assert events[-1]["status"] == "failed"
    assert "not connected" in events[-1]["steps"][0]["error_message"].lower()


def test_delete_workflow_cascades_to_its_step_tasks(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={"name": "To delete", "steps": [{"title": "a"}, {"title": "b"}]},
        headers=alice,
    ).json()
    step_id = workflow["steps"][0]["id"]

    r = client.delete(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}", headers=alice)
    assert r.status_code == 204

    r2 = client.get(f"/api/v1/projects/{project['id']}/tasks/{step_id}", headers=alice)
    assert r2.status_code == 404
