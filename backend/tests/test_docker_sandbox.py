"""Unlike every other adapter in this project, the Docker Sandbox adapter
can actually succeed on this machine (it has a real, reachable Docker
daemon) -- so these tests exercise real isolated container execution end
to end, not just the honest-failure path. They skip (never fail) if
Docker genuinely isn't available in a given test environment."""

import time

import pytest

from app.services.agent_runtime.adapters import DockerSandboxAdapter
from app.services.agent_runtime.base import ExecutionResult


def _docker_available() -> bool:
    return DockerSandboxAdapter().health_check(None).connected


requires_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker daemon is not reachable in this environment"
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


def _wait_for_terminal_status(client, project_id, task_id, headers, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/projects/{project_id}/tasks/{task_id}", headers=headers).json()
        if body["status"] != "running":
            return body
        time.sleep(0.2)
    raise AssertionError("task did not reach a terminal status in time")


def test_health_check_reports_real_docker_version():
    result = DockerSandboxAdapter().health_check(None)
    if not result.connected:
        pytest.skip("Docker daemon is not reachable in this environment")
    assert result.version != ""


@requires_docker
def test_direct_sandbox_execution_runs_a_real_command():
    result = DockerSandboxAdapter().start_execution("echo hello-from-sandbox", None)
    assert result.succeeded is True
    assert "hello-from-sandbox" in result.output


@requires_docker
def test_sandbox_has_no_network_access():
    """Proves `--network none` is real isolation, not just a label: a DNS
    lookup from inside the container must genuinely fail."""
    result = DockerSandboxAdapter().start_execution(
        "python3 -c \"import socket; socket.create_connection(('example.com', 80), timeout=3)\"",
        None,
    )
    assert result.succeeded is False
    assert "gaierror" in result.error or "Temporary failure in name resolution" in result.error


@requires_docker
def test_sandbox_execution_failure_is_reported_honestly():
    result = DockerSandboxAdapter().start_execution("exit 7", None)
    assert result.succeeded is False


@requires_docker
def test_task_against_a_real_docker_sandbox_connection_actually_succeeds(client):
    """This is the first non-mocked task-execution test in this project
    whose honest, non-mocked outcome is a real success -- every other
    local-runtime adapter fails honestly on this machine because its CLI
    isn't installed; Docker's daemon genuinely is reachable."""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "docker_sandbox", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={
            "title": "Say hi from the sandbox",
            "description": "echo real-sandbox-output",
            "coding_agent_connection_id": connection["id"],
        },
        headers=alice,
    ).json()

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/start", headers=alice)
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    body = _wait_for_terminal_status(client, project["id"], task["id"], alice)
    assert body["status"] == "completed"
    assert "real-sandbox-output" in body["output"]
    assert body["error_message"] == ""


@requires_docker
def test_cancelling_a_real_sandboxed_task_actually_stops_the_container():
    """A genuine (non-mocked) cancellation test: the sandboxed command
    sleeps, the real `should_cancel` flag flips mid-run, and the real
    `docker run` client process -- and the container it's running -- is
    actually terminated early rather than left running to completion."""
    chunks: list[str] = []
    cancel_after_first_chunk = {"flag": False}

    def on_chunk(text: str) -> None:
        chunks.append(text)
        cancel_after_first_chunk["flag"] = True

    def should_cancel() -> bool:
        return cancel_after_first_chunk["flag"]

    started = time.monotonic()
    result: ExecutionResult = DockerSandboxAdapter().start_execution_streaming(
        "echo starting; sleep 30; echo should-never-print", None, on_chunk, should_cancel
    )
    elapsed = time.monotonic() - started

    assert result.succeeded is False
    assert result.error == "Cancelled by user."
    assert "should-never-print" not in result.output
    # If cancellation genuinely killed the container instead of waiting the
    # full `sleep 30` out, this returns in well under that window.
    assert elapsed < 20
