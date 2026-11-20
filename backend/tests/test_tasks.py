import json
import subprocess
import time

from app.services.agent_runtime.adapters import ClaudeCodeAdapter
from app.services.agent_runtime.base import ExecutionResult, HealthCheckResult
from app.services.git_provider.base import (
    BranchProtectionSummary,
    CommitSummary,
    GitProviderError,
    PullRequestSummary,
    RepositorySummary,
)
from app.services.git_provider.github_app import GitHubAppAdapter


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
    """No `codex` CLI is installed here and no API key is configured, so
    starting a task against a real (non-mocked) local-runtime connection
    must fail with the real reason — never a simulated success. (Not
    `claude_code`: this dev machine has the real Claude Code CLI installed
    for live testing.)"""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "codex", "connection_mode": "local_runtime"},
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
    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
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

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
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


def _run_git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _seed_remote_repo(tmp_path):
    """A real local Git repository standing in for a remote GitHub repo."""
    repo = tmp_path / "remote"
    repo.mkdir()
    _run_git(["init", "-b", "main"], repo)
    _run_git(["config", "user.email", "seed@example.com"], repo)
    _run_git(["config", "user.name", "Seed"], repo)
    (repo / "README.md").write_text("hello\n")
    _run_git(["add", "-A"], repo)
    _run_git(["commit", "-m", "Initial commit"], repo)
    return repo


def _connect_repository(client, headers, org, project, remote_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    monkeypatch.setattr(
        GitHubAppAdapter, "get_authenticated_clone_url", lambda self, *a, **k: str(remote_repo)
    )
    import app.services.git_worktree as git_worktree

    monkeypatch.setattr(git_worktree, "_worktree_root", lambda: tmp_path / "worktrees")

    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=headers,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=headers,
    )


def test_task_with_a_connected_repository_runs_in_a_real_git_worktree(client, monkeypatch, tmp_path):
    """Phase 14: when the project has a connected repository, a task runs
    against a real, isolated checkout on its own branch -- not a bare
    prompt with no codebase. Only the network edge (which URL the GitHub
    App adapter hands back) is stubbed; the clone, branch, file edit,
    commit and diff are all genuine `git` operations."""
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        assert cwd is not None
        with open(f"{cwd}/new_feature.py", "w") as f:
            f.write("print('real change')\n")
        on_chunk("Added new_feature.py")
        return ExecutionResult(succeeded=True, output="Added new_feature.py")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

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
    assert body["git_branch_name"].startswith("sf-task-")
    assert body["git_base_branch"] == "main"
    assert body["git_changed_files"] == ["new_feature.py"]

    diff = client.get(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/diff", headers=alice).json()
    assert diff["git_changed_files"] == ["new_feature.py"]
    assert "real change" in diff["git_diff"]


def test_task_with_no_filesystem_changes_reports_an_empty_diff(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        on_chunk("Looked around, changed nothing")
        return ExecutionResult(succeeded=True, output="Looked around, changed nothing")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

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
        json={"title": "Investigate", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()

    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)

    assert body["status"] == "completed"
    assert body["git_branch_name"].startswith("sf-task-")
    assert body["git_changed_files"] == []


def test_task_with_real_changes_pushes_its_branch_and_opens_a_real_pull_request(client, monkeypatch, tmp_path):
    """Phase 15: once the task actually changed files, its branch is pushed
    to the real remote (a genuine `git push`, verified below against the
    local repo standing in for GitHub) and a pull request is opened via
    the Git Provider Interface -- only `create_pull_request` itself is
    stubbed, since opening a real GitHub PR needs a real GitHub repo."""
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        with open(f"{cwd}/new_feature.py", "w") as f:
            f.write("print('real change')\n")
        on_chunk("Added new_feature.py")
        return ExecutionResult(succeeded=True, output="Added new_feature.py")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

    captured_pr_request = {}

    def fake_create_pull_request(self, installation_id, owner, name, head_branch, base_branch, title, body=""):
        captured_pr_request.update(
            installation_id=installation_id, owner=owner, name=name,
            head_branch=head_branch, base_branch=base_branch, title=title, body=body,
        )
        return PullRequestSummary(number=7, url="https://github.com/acme/widgets/pull/7")

    monkeypatch.setattr(GitHubAppAdapter, "create_pull_request", fake_create_pull_request)

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
    assert body["git_pr_number"] == 7
    assert body["git_pr_url"] == "https://github.com/acme/widgets/pull/7"
    assert captured_pr_request["owner"] == "acme"
    assert captured_pr_request["name"] == "widgets"
    assert captured_pr_request["head_branch"] == body["git_branch_name"]
    assert captured_pr_request["base_branch"] == "main"
    assert captured_pr_request["title"] == "Add a feature"

    branches = subprocess.run(
        ["git", "branch", "--list", body["git_branch_name"]], cwd=remote_repo, capture_output=True, text=True
    )
    assert body["git_branch_name"] in branches.stdout


def test_a_pull_request_failure_is_reported_honestly_without_overturning_task_success(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        with open(f"{cwd}/new_feature.py", "w") as f:
            f.write("print('real change')\n")
        on_chunk("Added new_feature.py")
        return ExecutionResult(succeeded=True, output="Added new_feature.py")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

    def fake_create_pull_request(self, installation_id, owner, name, head_branch, base_branch, title, body=""):
        raise GitProviderError("A pull request already exists for acme:sf-task.")

    monkeypatch.setattr(GitHubAppAdapter, "create_pull_request", fake_create_pull_request)

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
    assert body["git_pr_url"] == ""
    assert body["git_pr_number"] == 0
    assert "pull request already exists" in body["error_message"].lower()


def test_task_pull_request_records_the_real_branch_protection_rules(client, monkeypatch, tmp_path):
    """Phase 18: right after opening the PR, the base branch's real
    branch protection rules are recorded too -- informational only, never
    enforced by this backend."""
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        with open(f"{cwd}/new_feature.py", "w") as f:
            f.write("print('real change')\n")
        on_chunk("Added new_feature.py")
        return ExecutionResult(succeeded=True, output="Added new_feature.py")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)
    monkeypatch.setattr(
        GitHubAppAdapter,
        "create_pull_request",
        lambda self, *a, **k: PullRequestSummary(number=7, url="https://github.com/acme/widgets/pull/7"),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_protection",
        lambda self, *a, **k: BranchProtectionSummary(
            protected=True, required_status_checks=["ci/build"], required_approving_review_count=2
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
    assert body["git_base_branch_protected"] is True
    assert body["git_required_status_checks"] == ["ci/build"]
    assert body["git_required_approving_reviews"] == 2


def test_task_branch_protection_lookup_failure_is_reported_honestly_without_overturning_task_success(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        with open(f"{cwd}/new_feature.py", "w") as f:
            f.write("print('real change')\n")
        on_chunk("Added new_feature.py")
        return ExecutionResult(succeeded=True, output="Added new_feature.py")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)
    monkeypatch.setattr(
        GitHubAppAdapter,
        "create_pull_request",
        lambda self, *a, **k: PullRequestSummary(number=7, url="https://github.com/acme/widgets/pull/7"),
    )

    def fake_get_branch_protection(self, *a, **k):
        raise GitProviderError("Could not reach GitHub.")

    monkeypatch.setattr(GitHubAppAdapter, "get_branch_protection", fake_get_branch_protection)

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
    assert body["git_pr_number"] == 7
    assert body["git_base_branch_protected"] is False
    assert "could not read the base branch's protection rules" in body["error_message"].lower()


def test_worktree_preparation_failure_fails_the_task_honestly(client, monkeypatch, tmp_path):
    """A connected repository whose authenticated clone URL cannot be
    obtained (e.g. the GitHub App stopped being configured between
    connecting the repo and starting the task) must fail the task with
    the real reason -- never a fabricated success with no codebase."""
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    remote_repo = _seed_remote_repo(tmp_path)
    _connect_repository(client, alice, org, project, remote_repo, monkeypatch, tmp_path)

    # Simulate the App becoming unreachable right before the task starts.
    def _fail(self, *a, **k):
        from app.services.git_provider.base import GitProviderError

        raise GitProviderError("GitHub App not configured on this backend.")

    monkeypatch.setattr(GitHubAppAdapter, "get_authenticated_clone_url", _fail)

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

    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)

    assert body["status"] == "failed"
    assert body["output"] == ""
    assert "could not prepare a git worktree" in body["error_message"].lower()
    assert body["git_branch_name"] == ""
