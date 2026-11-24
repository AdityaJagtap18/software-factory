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


def test_create_and_list_approval(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/approvals",
        json={"category": "knowledge_update", "title": "Promote doc to project", "priority": "medium"},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    approval = r.json()
    assert approval["status"] == "pending"
    assert approval["requested_by_user_id"] is not None

    listed = client.get(f"/api/v1/projects/{project['id']}/approvals", headers=alice).json()
    assert len(listed) == 1
    assert listed[0]["id"] == approval["id"]


def test_decide_approval_records_real_decision(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    approval = client.post(
        f"/api/v1/projects/{project['id']}/approvals",
        json={"category": "prompt_change", "title": "Publish prompt v2"},
        headers=alice,
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/approvals/{approval['id']}/decide",
        json={"decision": "approved", "note": "looks good"},
        headers=alice,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["decision_note"] == "looks good"
    assert body["decided_by_user_id"] is not None
    assert body["decided_at"] is not None


def test_cannot_decide_an_already_decided_approval(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    approval = client.post(
        f"/api/v1/projects/{project['id']}/approvals",
        json={"category": "workflow_run", "title": "Run nightly workflow"},
        headers=alice,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/approvals/{approval['id']}/decide",
        json={"decision": "rejected"},
        headers=alice,
    )

    r = client.post(
        f"/api/v1/projects/{project['id']}/approvals/{approval['id']}/decide",
        json={"decision": "approved"},
        headers=alice,
    )
    assert r.status_code == 409


def test_viewer_cannot_decide_approval(client):
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
    approval = client.post(
        f"/api/v1/projects/{project['id']}/approvals",
        json={"category": "access_security", "title": "Grant admin access"},
        headers=alice,
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/approvals/{approval['id']}/decide",
        json={"decision": "approved"},
        headers=bob,
    )
    assert r.status_code == 403


def test_filter_approvals_by_status(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    a1 = client.post(
        f"/api/v1/projects/{project['id']}/approvals",
        json={"category": "model_action", "title": "Switch default model"},
        headers=alice,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/approvals",
        json={"category": "model_action", "title": "Add new model"},
        headers=alice,
    )
    client.post(
        f"/api/v1/projects/{project['id']}/approvals/{a1['id']}/decide",
        json={"decision": "approved"},
        headers=alice,
    )

    pending = client.get(
        f"/api/v1/projects/{project['id']}/approvals", params={"status": "pending"}, headers=alice
    ).json()
    assert len(pending) == 1
    assert pending[0]["title"] == "Add new model"


def test_opening_a_real_pull_request_creates_a_real_code_change_approval(client, monkeypatch, tmp_path):
    """P3-6: a task's real PR-open event (not a mock, not a fabricated
    record) must produce a real pending Approval row, so the Approval
    Center reflects genuine governance-worthy events rather than static
    mock data."""
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None, model=None):
        with open(f"{cwd}/new_feature.py", "w") as f:
            f.write("print('real change')\n")
        on_chunk("Added new_feature.py")
        return ExecutionResult(succeeded=True, output="Added new_feature.py")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)
    monkeypatch.setattr(
        GitHubAppAdapter,
        "create_pull_request",
        lambda self, installation_id, owner, name, head_branch, base_branch, title, body="": PullRequestSummary(
            number=9, url="https://github.com/acme/widgets/pull/9"
        ),
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
        json={"title": "Add a feature", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "completed"
    assert body["git_pr_number"] == 9

    approvals = client.get(f"/api/v1/projects/{project['id']}/approvals", headers=alice).json()
    code_change = [a for a in approvals if a["task_id"] == task["id"]]
    assert len(code_change) == 1
    assert code_change[0]["category"] == "code_change"
    assert code_change[0]["status"] == "pending"
    assert "#9" in code_change[0]["subtitle"]
