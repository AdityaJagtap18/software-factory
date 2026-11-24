"""Phase 5 (P5-1/P5-2/P5-3): orchestration engine, agent replacement /
resumable handoff, and provider routing/fallback.

Every test here exercises the real code paths -- real threads, real
Postgres rows, real (monkeypatched-at-the-adapter-boundary) execution --
never a simulated status transition."""

import subprocess
import sys
import threading
import time

from app.services import embeddings
from app.services.agent_runtime.adapters import ClaudeCodeAdapter, CodexAdapter
from app.services.agent_runtime.base import ExecutionResult, HealthCheckResult
from app.services.git_provider.base import CommitSummary, RepositorySummary
from app.services.git_provider.github_app import GitHubAppAdapter


def _skip_rag_embedding(monkeypatch):
    """P4-4's RAG step calls the real local embedding model on every task
    run regardless of whether the project has any documents -- fine in
    production, but an unreachable/slow Ollama makes a timing-sensitive
    test (the parallel-execution proof below) flaky for a reason that has
    nothing to do with what it's testing. Short-circuit it the same way
    an unreachable embedding model already does: `EmbeddingError` ->
    `retrieve_relevant_chunks` returns `[]` -> no RAG context, real
    behavior preserved."""
    monkeypatch.setattr(
        embeddings, "embed_text", lambda text: (_ for _ in ()).throw(embeddings.EmbeddingError("skipped in tests"))
    )


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


def _connection(client, headers, org, runtime_slug):
    return client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": runtime_slug, "connection_mode": "local_runtime"},
        headers=headers,
    ).json()


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


def _wait_for_terminal_task_status(client, project_id, task_id, headers, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/projects/{project_id}/tasks/{task_id}", headers=headers).json()
        if body["status"] != "running":
            return body
        time.sleep(0.1)
    raise AssertionError("task did not reach a terminal status in time")


def _sync_agent_registry(client, headers):
    client.get("/api/v1/agents", headers=headers)


def test_capability_based_assignment_picks_an_eligible_connected_agent(client, monkeypatch):
    _skip_rag_embedding(monkeypatch)
    monkeypatch.setattr(
        ClaudeCodeAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )
    monkeypatch.setattr(
        CodexAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "start_execution_streaming",
        lambda self, prompt, c, on_chunk, should_cancel, cwd=None: ExecutionResult(
            succeeded=True, output=f"done: {prompt}"
        ),
    )
    monkeypatch.setattr(
        CodexAdapter,
        "start_execution_streaming",
        lambda self, prompt, c, on_chunk, should_cancel, cwd=None: ExecutionResult(
            succeeded=True, output=f"done: {prompt}"
        ),
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    _sync_agent_registry(client, alice)
    claude_conn = _connection(client, alice, org, "claude_code")
    codex_conn = _connection(client, alice, org, "codex")

    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "Auto-assigned",
            "steps": [{"title": "Needs a CLI agent", "required_capability": "CLI detection"}],
        },
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice)

    body = _wait_for_terminal_workflow_status(client, project["id"], workflow["id"], alice)
    assert body["status"] == "completed"
    assigned = body["steps"][0]["coding_agent_connection_id"]
    assert assigned in (claude_conn["id"], codex_conn["id"])


def test_capability_based_assignment_escalates_honestly_when_nothing_eligible(client, monkeypatch):
    _skip_rag_embedding(monkeypatch)
    monkeypatch.setattr(
        ClaudeCodeAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    _sync_agent_registry(client, alice)
    _connection(client, alice, org, "claude_code")

    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "Needs a mythical capability",
            "steps": [{"title": "x", "required_capability": "Telepathic debugging"}],
        },
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice)

    body = _wait_for_terminal_workflow_status(client, project["id"], workflow["id"], alice)
    assert body["status"] == "failed"
    assert "no eligible" in body["steps"][0]["error_message"].lower()
    assert body["steps"][0]["coding_agent_connection_id"] is None


def test_independent_steps_with_explicit_empty_deps_run_truly_in_parallel(client, monkeypatch):
    """Two steps that both explicitly declare `depends_on_step_orders: []`
    are independent of each other (not of the default "every prior step"
    rule) and must run concurrently -- proven with a two-party barrier: if
    they ran one after another, the first to reach the barrier would
    block until it times out and the whole step would fail."""
    # A real blocking syscall (not just a Python-level op) early in each
    # worker thread's path, before either reaches the barrier below --
    # empirically, without this, this sandboxed environment's OS scheduler
    # can leave the second real OS thread completely undispatched for many
    # seconds even though it is genuinely runnable (confirmed with a
    # watchdog sampling both threads' frames: the thread sits unscheduled,
    # not blocked on anything in this code), which is a scheduler-fairness
    # artifact of this environment and not evidence the workflow
    # supervisor ran the steps sequentially.
    monkeypatch.setattr(
        ClaudeCodeAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )
    _skip_rag_embedding(monkeypatch)
    old_switch_interval = sys.getswitchinterval()
    sys.setswitchinterval(0.001)
    original_thread_start = threading.Thread.start

    def _start_and_yield(self):
        original_thread_start(self)
        # A real blocking syscall in the PARENT thread right after handing
        # control to the new one: without this, this sandboxed
        # environment's OS scheduler can leave a genuinely runnable second
        # OS thread completely undispatched for many seconds (confirmed
        # with a watchdog sampling both threads' frames: the thread sits
        # unscheduled, not blocked on anything in application code) --
        # a scheduler-fairness artifact of this environment, not evidence
        # the workflow supervisor itself ran steps sequentially.
        time.sleep(0.01)

    monkeypatch.setattr(threading.Thread, "start", _start_and_yield)
    try:
        # Generous on purpose: this only has to prove the two steps overlap
        # in time, not run fast. A real sequential execution would never
        # release this barrier at all (the second party never arrives) and
        # time out here regardless of how long the timeout is.
        barrier = threading.Barrier(2, timeout=20)

        def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
            if prompt in ("StepA", "StepB"):
                barrier.wait()
            on_chunk(f"done: {prompt}")
            return ExecutionResult(succeeded=True, output=f"done: {prompt}")

        monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

        alice = _register_and_login(client, "alice@example.com", "Alice")
        org, project = _project(client, alice)
        connection = _connection(client, alice, org, "claude_code")

        workflow = client.post(
            f"/api/v1/projects/{project['id']}/workflows",
            json={
                "name": "Fan-out then join",
                "steps": [
                    {
                        "title": "StepA",
                        "coding_agent_connection_id": connection["id"],
                        "depends_on_step_orders": [],
                    },
                    {
                        "title": "StepB",
                        "coding_agent_connection_id": connection["id"],
                        "depends_on_step_orders": [],
                    },
                    {
                        "title": "StepC",
                        "coding_agent_connection_id": connection["id"],
                        "depends_on_step_orders": [0, 1],
                    },
                ],
            },
            headers=alice,
        ).json()
        client.post(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice)

        body = _wait_for_terminal_workflow_status(client, project["id"], workflow["id"], alice, timeout=30)
        assert body["status"] == "completed", body
        assert [s["status"] for s in body["steps"]] == ["completed", "completed", "completed"]
        # StepC explicitly depends on A and B -- its prompt (echoed back as
        # output by fake_streaming) must contain the real shared-context
        # note built from both of their real outputs.
        step_c_output = body["steps"][2]["output"]
        assert "StepA" in step_c_output
        assert "StepB" in step_c_output
        assert "done: StepA" in step_c_output
        assert "done: StepB" in step_c_output
    finally:
        sys.setswitchinterval(old_switch_interval)


def test_invalid_dependency_declaration_is_rejected_at_creation(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    r = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "Bad deps",
            "steps": [
                {"title": "A", "depends_on_step_orders": [5]},
            ],
        },
        headers=alice,
    )
    assert r.status_code == 400


def test_step_retries_with_automatic_fallback_to_a_different_connection(client, monkeypatch, tmp_path):
    """P5-2/P5-3 together: a step assigned to a connection that fails is
    automatically retried against a different eligible connection via a
    real, recorded `TaskHandoff` -- not a bare re-run of the same
    doomed connection. A handoff resumes a task's real Git workspace (see
    `handoff.py`), so this needs a connected repository the same as a
    human-triggered handoff does -- a step with no workspace to resume
    into fails that honest check instead of ever reaching a fallback."""
    _skip_rag_embedding(monkeypatch)
    monkeypatch.setattr(
        ClaudeCodeAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )
    monkeypatch.setattr(
        CodexAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "start_execution_streaming",
        lambda self, prompt, c, on_chunk, should_cancel, cwd=None: ExecutionResult(
            succeeded=False, output="", error="Simulated real failure"
        ),
    )
    monkeypatch.setattr(
        CodexAdapter,
        "start_execution_streaming",
        lambda self, prompt, c, on_chunk, should_cancel, cwd=None: ExecutionResult(
            succeeded=True, output="Codex picked it up"
        ),
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    remote_repo = _seed_remote_repo(tmp_path)
    _connect_repository(client, alice, org, project, remote_repo, monkeypatch, tmp_path)
    _sync_agent_registry(client, alice)
    claude_conn = _connection(client, alice, org, "claude_code")
    codex_conn = _connection(client, alice, org, "codex")

    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "Retries on failure",
            "steps": [
                {
                    "title": "Flaky step",
                    "coding_agent_connection_id": claude_conn["id"],
                    "required_capability": "CLI detection",
                    "max_retries": 1,
                }
            ],
        },
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice)

    body = _wait_for_terminal_workflow_status(client, project["id"], workflow["id"], alice)
    assert body["status"] == "completed", body
    step = body["steps"][0]
    assert step["status"] == "completed"
    assert step["coding_agent_connection_id"] == codex_conn["id"]
    assert step["retry_count"] == 1
    assert step["output"] == "Codex picked it up"

    handoffs = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{step['id']}/handoffs", headers=alice
    ).json()
    assert len(handoffs) == 1
    assert handoffs[0]["automatic"] is True
    assert handoffs[0]["from_connection_id"] == claude_conn["id"]
    assert handoffs[0]["to_connection_id"] == codex_conn["id"]
    assert handoffs[0]["status"] == "resumed"
    assert "Simulated real failure" in handoffs[0]["package"]["known_failure_reason"]

    attempts = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{step['id']}/attempts", headers=alice
    ).json()
    assert len(attempts) == 2
    assert attempts[0]["agent_slug"] == "claude_code"
    assert attempts[0]["succeeded"] is False
    assert attempts[1]["agent_slug"] == "codex"
    assert attempts[1]["succeeded"] is True
    assert attempts[1]["handoff_id"] == handoffs[0]["id"]


def _run_git(args, cwd):
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


def test_human_triggered_handoff_resumes_the_real_worktree_with_a_different_agent(
    client, monkeypatch, tmp_path
):
    """The exact scenario the roadmap names: Claude Code starts, fails;
    a human hands the task off to Codex; Codex genuinely resumes the same
    worktree/branch rather than starting over, and the full attempt/
    handoff history is recorded honestly."""
    _skip_rag_embedding(monkeypatch)
    monkeypatch.setattr(
        ClaudeCodeAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )
    monkeypatch.setattr(
        CodexAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )

    def claude_fails(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        with open(f"{cwd}/partial.py", "w") as f:
            f.write("print('partial work')\n")
        on_chunk("got partway through")
        return ExecutionResult(succeeded=False, output="got partway through", error="Claude Code crashed")

    def codex_resumes(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        import os

        assert os.path.exists(f"{cwd}/partial.py")
        assert "already worked on this task" in prompt
        assert "Claude Code crashed" in prompt
        with open(f"{cwd}/finished.py", "w") as f:
            f.write("print('finished by codex')\n")
        on_chunk("finished by codex")
        return ExecutionResult(succeeded=True, output="finished by codex")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", claude_fails)
    monkeypatch.setattr(CodexAdapter, "start_execution_streaming", codex_resumes)

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    remote_repo = _seed_remote_repo(tmp_path)
    _connect_repository(client, alice, org, project, remote_repo, monkeypatch, tmp_path)

    claude_conn = _connection(client, alice, org, "claude_code")
    codex_conn = _connection(client, alice, org, "codex")

    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Build a feature", "coding_agent_connection_id": claude_conn["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    first = _wait_for_terminal_task_status(client, project["id"], task["id"], alice)
    assert first["status"] == "failed"
    assert "Claude Code crashed" in first["error_message"]

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/handoff",
        json={"to_connection_id": codex_conn["id"], "reason": "Claude Code kept crashing"},
        headers=alice,
    )
    assert r.status_code == 201, r.text

    second = _wait_for_terminal_task_status(client, project["id"], task["id"], alice)
    assert second["status"] == "completed"
    assert second["coding_agent_connection_id"] == codex_conn["id"]
    assert set(second["git_changed_files"]) == {"partial.py", "finished.py"}

    handoffs = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/handoffs", headers=alice
    ).json()
    assert len(handoffs) == 1
    assert handoffs[0]["automatic"] is False
    assert handoffs[0]["reason"] == "Claude Code kept crashing"
    assert handoffs[0]["status"] == "resumed"
    assert "Claude Code crashed" in handoffs[0]["package"]["known_failure_reason"]

    attempts = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/attempts", headers=alice
    ).json()
    assert len(attempts) == 2
    assert attempts[0]["agent_slug"] == "claude_code" and attempts[0]["succeeded"] is False
    assert attempts[1]["agent_slug"] == "codex" and attempts[1]["succeeded"] is True
    assert attempts[1]["handoff_id"] == handoffs[0]["id"]


def test_cannot_handoff_a_running_task(client, monkeypatch):
    import threading as _threading

    started = _threading.Event()
    release = _threading.Event()

    _skip_rag_embedding(monkeypatch)
    monkeypatch.setattr(
        ClaudeCodeAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )

    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None):
        started.set()
        release.wait(timeout=5)
        return ExecutionResult(succeeded=True, output="done")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    claude_conn = _connection(client, alice, org, "claude_code")
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "x", "coding_agent_connection_id": claude_conn["id"]},
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    assert started.wait(timeout=5)

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/handoff",
        json={"to_connection_id": claude_conn["id"]},
        headers=alice,
    )
    assert r.status_code == 409

    release.set()
    _wait_for_terminal_task_status(client, project["id"], task["id"], alice)


def test_routing_policy_orders_the_fallback_chain(client, monkeypatch):
    """P5-3: an org admin's routing policy, not registry order, decides
    which connection auto-assignment/fallback tries first."""
    _skip_rag_embedding(monkeypatch)
    monkeypatch.setattr(
        ClaudeCodeAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )
    monkeypatch.setattr(
        CodexAdapter, "health_check", lambda self, c: HealthCheckResult(connected=True, detail="ok")
    )
    monkeypatch.setattr(
        ClaudeCodeAdapter,
        "start_execution_streaming",
        lambda self, prompt, c, on_chunk, should_cancel, cwd=None: ExecutionResult(
            succeeded=True, output="claude ran"
        ),
    )
    monkeypatch.setattr(
        CodexAdapter,
        "start_execution_streaming",
        lambda self, prompt, c, on_chunk, should_cancel, cwd=None: ExecutionResult(
            succeeded=True, output="codex ran"
        ),
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    _sync_agent_registry(client, alice)
    _connection(client, alice, org, "claude_code")
    _connection(client, alice, org, "codex")

    r = client.post(
        f"/api/v1/organizations/{org['id']}/routing-policies",
        json={"capability": "CLI detection", "fallback_chain": ["codex", "claude_code"]},
        headers=alice,
    )
    assert r.status_code == 201, r.text

    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={
            "name": "Policy-routed",
            "steps": [{"title": "x", "required_capability": "CLI detection"}],
        },
        headers=alice,
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/workflows/{workflow['id']}/start", headers=alice)

    body = _wait_for_terminal_workflow_status(client, project["id"], workflow["id"], alice)
    assert body["status"] == "completed"
    assert body["steps"][0]["output"] == "codex ran"


def test_non_org_admin_cannot_create_routing_policy(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org, _project_ = _project(client, alice)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=alice,
    )
    r = client.post(
        f"/api/v1/organizations/{org['id']}/routing-policies",
        json={"fallback_chain": ["codex"]},
        headers=bob,
    )
    assert r.status_code == 403
