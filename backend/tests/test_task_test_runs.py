from app.services.agent_runtime.adapters import ClaudeCodeAdapter
from app.services.agent_runtime.base import ExecutionResult, HealthCheckResult
from app.services.git_provider.base import PullRequestSummary
from app.services.git_provider.github_app import GitHubAppAdapter
from tests.test_tasks import _connect_repository, _seed_remote_repo, _wait_for_terminal_status


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


def test_a_completed_task_gets_a_real_test_run_against_its_own_worktree(client, monkeypatch, tmp_path):
    """P3-1: once a task with a repository connection finishes, its real
    worktree (which this test seeds with one passing pytest test) gets a
    real `pytest -q` run -- not a fabricated result."""
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None, model=None):
        with open(f"{cwd}/test_new_feature.py", "w") as f:
            f.write("def test_it():\n    assert 1 + 1 == 2\n")
        on_chunk("Added test_new_feature.py")
        return ExecutionResult(succeeded=True, output="Added test_new_feature.py")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)
    monkeypatch.setattr(
        GitHubAppAdapter,
        "create_pull_request",
        lambda self, *a, **k: PullRequestSummary(number=1, url="https://github.com/acme/widgets/pull/1"),
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    remote_repo = _seed_remote_repo(tmp_path)
    _connect_repository(client, alice, org, project, remote_repo, monkeypatch, tmp_path)

    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Add a test", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "completed"

    runs = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/test-runs", headers=alice
    ).json()
    assert len(runs) == 1
    assert runs[0]["framework"] == "pytest"
    assert runs[0]["ran"] is True
    assert runs[0]["passed"] == 1
    assert runs[0]["failed"] == 0


def test_trigger_test_run_without_a_worktree_reports_honestly(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "No worktree"}, headers=alice
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/test-runs", headers=alice
    )
    assert r.status_code == 409
