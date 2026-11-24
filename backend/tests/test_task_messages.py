"""P3-4: end-to-end verification of the multi-turn task conversation
(`TaskMessage`). This was flagged in the roadmap as "appears already
implemented... not independently confirmed working end-to-end" -- this
file is that independent confirmation, covering persistence, ordering,
authorization, and the real follow-up execution path (resume worktree,
re-invoke the adapter, record the real outcome)."""

import time

from app.services.agent_runtime.adapters import ClaudeCodeAdapter
from app.services.agent_runtime.base import ExecutionResult, HealthCheckResult
from app.services.git_provider.base import CommitSummary, RepositorySummary
from app.services.git_provider.github_app import GitHubAppAdapter


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


def _wait_for_terminal_status(client, project_id, task_id, headers, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/projects/{project_id}/tasks/{task_id}", headers=headers).json()
        if body["status"] != "running":
            return body
        time.sleep(0.1)
    raise AssertionError("task did not reach a terminal status in time")


def _run_git(args, cwd):
    import subprocess

    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _seed_remote_repo(tmp_path):
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


def _wait_for_messages(client, project_id, task_id, headers, min_count, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(
            f"/api/v1/projects/{project_id}/tasks/{task_id}/messages", headers=headers
        ).json()
        if len(body) >= min_count:
            return body
        time.sleep(0.1)
    raise AssertionError(f"did not observe {min_count} messages in time")


def test_messages_list_is_empty_for_a_fresh_task(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Do thing"}, headers=alice
    ).json()

    r = client.get(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/messages", headers=alice)
    assert r.status_code == 200
    assert r.json() == []


def test_followup_on_a_task_with_no_workspace_fails_honestly_and_is_recorded(client):
    """A task that was never started (no git worktree to resume) must fail
    the follow-up honestly, not silently no-op or fake success -- and the
    real user instruction plus the real system failure must both persist
    and be readable back in order."""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Do thing"}, headers=alice
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/messages",
        json={"content": "please also fix the tests"},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "user"
    assert r.json()["content"] == "please also fix the tests"

    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "failed"
    assert "no existing workspace" in body["error_message"].lower()

    messages = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/messages", headers=alice
    ).json()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "please also fix the tests"
    assert messages[1]["role"] == "system"
    assert "no existing workspace" in messages[1]["content"].lower()
    # Ordering is by real creation time, not insertion order of the test.
    assert messages[0]["created_at"] <= messages[1]["created_at"]


def test_followup_resumes_the_real_worktree_and_records_a_real_agent_reply(client, monkeypatch, tmp_path):
    """The full real round trip: start a task against a real connected repo
    (first turn), then send a follow-up instruction (second turn) -- the
    follow-up must resume the SAME git worktree (the first turn's file is
    still there on disk) and append a real AGENT message with the second
    adapter run's real output, readable back via GET /messages in the
    correct conversation order."""
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    calls = {"n": 0}

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        calls["n"] += 1
        if calls["n"] == 1:
            with open(f"{cwd}/first.py", "w") as f:
                f.write("print('first turn')\n")
            on_chunk("Added first.py")
            return ExecutionResult(succeeded=True, output="Added first.py")
        # Second turn (the follow-up): the first turn's file must already
        # be there -- this is what "resume the existing worktree" means.
        import os

        assert os.path.exists(f"{cwd}/first.py")
        assert "continue in it, don't start over" in prompt
        assert "also add a test" in prompt
        with open(f"{cwd}/second.py", "w") as f:
            f.write("print('second turn')\n")
        on_chunk("Added second.py")
        return ExecutionResult(succeeded=True, output="Added second.py")

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
    first_result = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert first_result["status"] == "completed"

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/messages",
        json={"content": "also add a test"},
        headers=alice,
    )
    assert r.status_code == 201, r.text

    second_result = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert second_result["status"] == "completed"
    assert set(second_result["git_changed_files"]) == {"first.py", "second.py"}

    messages = _wait_for_messages(client, project["id"], task["id"], alice, min_count=2)
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "also add a test"
    assert messages[1]["role"] == "agent"
    assert messages[1]["content"] == "Added second.py"
    assert calls["n"] == 2


def test_cannot_post_followup_while_task_is_already_running(client, monkeypatch):
    import threading

    started = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "health_check",
        lambda self, credential_value: HealthCheckResult(connected=True, detail="ok"),
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        started.set()
        release.wait(timeout=5)
        return ExecutionResult(succeeded=True, output="done")

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
        json={"title": "Do thing", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()

    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    assert started.wait(timeout=5)

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/messages",
        json={"content": "hurry up"},
        headers=alice,
    )
    assert r.status_code == 409

    release.set()
    _wait_for_terminal_status(client, project["id"], task["id"], alice)


def test_viewer_cannot_post_a_followup_message(client):
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
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Do thing"}, headers=alice
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/messages",
        json={"content": "x"},
        headers=bob,
    )
    assert r.status_code == 403


def test_non_project_member_cannot_read_or_post_messages(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    mallory = _register_and_login(client, "mallory@example.com", "Mallory")
    _org, project = _project(client, alice)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Do thing"}, headers=alice
    ).json()

    r = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/messages", headers=mallory
    )
    assert r.status_code == 403

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/messages",
        json={"content": "x"},
        headers=mallory,
    )
    assert r.status_code == 403


def test_unauthenticated_request_is_rejected(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Do thing"}, headers=alice
    ).json()

    r = client.get(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/messages")
    assert r.status_code == 401
