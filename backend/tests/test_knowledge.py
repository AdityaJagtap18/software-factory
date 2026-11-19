import pytest

from app.services import knowledge_graph


def _neo4j_available() -> bool:
    ok, _detail = knowledge_graph.health_check()
    return ok


requires_neo4j = pytest.mark.skipif(
    not _neo4j_available(), reason="Neo4j is not reachable in this environment"
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


@requires_neo4j
def test_sync_and_query_a_real_graph_round_trip(client):
    """Proves the sync endpoint writes genuine nodes/relationships into a
    real Neo4j instance, and the graph endpoint reads them straight back
    -- not a client-side fabrication."""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _project(client, alice)
    connection = client.post(
        f"/api/v1/organizations/{org['id']}/coding-agent-connections",
        json={"runtime_slug": "claude_code", "connection_mode": "local_runtime"},
        headers=alice,
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        json={"title": "Fix bug", "coding_agent_connection_id": connection["id"]},
        headers=alice,
    ).json()
    workflow = client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={"name": "Ship it", "steps": [{"title": "Step one"}]},
        headers=alice,
    ).json()

    sync = client.post(f"/api/v1/projects/{project['id']}/knowledge/sync", headers=alice)
    assert sync.status_code == 200
    body = sync.json()
    assert body["connected"] is True
    assert body["nodes_synced"] > 0
    assert body["relationships_synced"] > 0
    assert body["synced_at"] is not None

    graph = client.get(f"/api/v1/projects/{project['id']}/knowledge/graph", headers=alice).json()
    assert graph["connected"] is True

    node_ids = {n["id"] for n in graph["nodes"]}
    assert str(project["id"]) == project["id"]  # sanity
    assert project["id"] in node_ids
    assert task["id"] in node_ids
    assert workflow["id"] in node_ids
    assert connection["id"] in node_ids

    edge_types = {(e["source"], e["target"], e["type"]) for e in graph["edges"]}
    assert (project["id"], task["id"], "HAS_TASK") in edge_types
    assert (project["id"], workflow["id"], "HAS_WORKFLOW") in edge_types
    assert (task["id"], connection["id"], "ASSIGNED_TO") in edge_types


@requires_neo4j
def test_sync_is_idempotent(client):
    """Syncing twice must not double the node/relationship count -- MERGE,
    never duplicate, real-world records."""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Task A"}, headers=alice
    )

    first = client.post(f"/api/v1/projects/{project['id']}/knowledge/sync", headers=alice).json()
    second = client.post(f"/api/v1/projects/{project['id']}/knowledge/sync", headers=alice).json()

    assert first["nodes_synced"] == second["nodes_synced"]
    assert first["relationships_synced"] == second["relationships_synced"]


def test_viewer_without_project_access_cannot_sync(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    _org, project = _project(client, alice)

    r = client.post(f"/api/v1/projects/{project['id']}/knowledge/sync", headers=bob)
    assert r.status_code == 403


def test_graph_endpoint_requires_project_access(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    _org, project = _project(client, alice)

    r = client.get(f"/api/v1/projects/{project['id']}/knowledge/graph", headers=bob)
    assert r.status_code == 403
