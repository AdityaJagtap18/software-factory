import uuid
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.workflow import Workflow, WorkflowStatus
from app.services import knowledge_graph


def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_summary_counts_are_real_and_scoped_to_my_access(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")

    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=alice
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Task A"}, headers=alice
    )
    client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Task B"}, headers=alice
    )

    alice_summary = client.get("/api/v1/dashboard/summary", headers=alice).json()
    assert alice_summary["organizations"] == 1
    assert alice_summary["projects"] == 1
    assert alice_summary["tasks_total"] == 2
    assert alice_summary["tasks_running"] == 0
    assert alice_summary["workflows_total"] == 0
    assert len(alice_summary["recent_activity"]) > 0

    # Bob has no access to Alice's org/project at all -- his dashboard must
    # be genuinely empty, never show Alice's real counts.
    bob_summary = client.get("/api/v1/dashboard/summary", headers=bob).json()
    assert bob_summary["organizations"] == 0
    assert bob_summary["projects"] == 0
    assert bob_summary["tasks_total"] == 0
    assert bob_summary["recent_activity"] == []


def test_dashboard_reports_real_running_workflow_progress(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=alice
    ).json()
    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={"name": "Ship it", "steps": [{"title": "Step one"}, {"title": "Step two"}]},
        headers=alice,
    ).json()

    # Deterministically put the workflow into a real "running" state with a
    # real elapsed duration, rather than racing the background Factory
    # Supervisor thread (which fails near-instantly with no connection
    # assigned) -- this isolates the dashboard's own aggregation logic.
    db = SessionLocal()
    db_workflow = db.get(Workflow, uuid.UUID(workflow["id"]))
    db_workflow.status = WorkflowStatus.RUNNING
    db_workflow.current_step_index = 1
    db_workflow.started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    db.commit()
    db.close()

    summary = client.get("/api/v1/dashboard/summary", headers=alice).json()
    assert summary["workflows_running"] == 1
    running = summary["running_workflows"][0]
    assert running["name"] == "Ship it"
    assert running["project_name"] == "FINTRIX"
    assert running["total_steps"] == 2
    assert running["current_step"] == 1
    assert running["progress_percent"] == 50
    assert running["elapsed_seconds"] >= 5


def test_dashboard_system_health_reports_real_dependency_status(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    summary = client.get("/api/v1/dashboard/summary", headers=alice).json()
    health_by_name = {h["name"]: h for h in summary["system_health"]}

    assert health_by_name["Postgres"]["connected"] is True

    neo4j_ok, _detail = knowledge_graph.health_check()
    assert health_by_name["Neo4j (knowledge graph)"]["connected"] == neo4j_ok


def test_dashboard_requires_authentication(client):
    r = client.get("/api/v1/dashboard/summary")
    assert r.status_code == 401
