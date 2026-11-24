"""P2-1 acceptance test: the Graph Access Service must scope every read to
the one project it was constructed for, even though every project shares
the same Neo4j database -- not just a 403 at the HTTP layer (already
covered by test_knowledge.py), but genuine data-level isolation."""

import pytest

from app.services import knowledge_graph

requires_neo4j = pytest.mark.skipif(
    not knowledge_graph.health_check()[0], reason="Neo4j is not reachable in this environment"
)


def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _project(client, headers, org_name, project_name):
    org = client.post("/api/v1/organizations", json={"name": org_name}, headers=headers).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": project_name}, headers=headers
    ).json()
    return org, project


@requires_neo4j
def test_graph_access_service_never_leaks_across_projects(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    _org_a, project_a = _project(client, alice, "Acme", "Alpha")
    _org_b, project_b = _project(client, bob, "Globex", "Beta")

    task_a = client.post(
        f"/api/v1/projects/{project_a['id']}/tasks", json={"title": "Alice's task"}, headers=alice
    ).json()
    task_b = client.post(
        f"/api/v1/projects/{project_b['id']}/tasks", json={"title": "Bob's task"}, headers=bob
    ).json()

    client.post(f"/api/v1/projects/{project_a['id']}/knowledge/sync", headers=alice)
    client.post(f"/api/v1/projects/{project_b['id']}/knowledge/sync", headers=bob)

    graph_a = client.get(f"/api/v1/projects/{project_a['id']}/knowledge/graph", headers=alice).json()
    graph_b = client.get(f"/api/v1/projects/{project_b['id']}/knowledge/graph", headers=bob).json()

    node_ids_a = {n["id"] for n in graph_a["nodes"]}
    node_ids_b = {n["id"] for n in graph_b["nodes"]}

    assert task_a["id"] in node_ids_a
    assert task_a["id"] not in node_ids_b
    assert task_b["id"] in node_ids_b
    assert task_b["id"] not in node_ids_a


def test_graph_access_service_has_no_project_id_parameter_on_any_method():
    """Structural guarantee: no method on GraphAccessService accepts a
    caller-supplied project id -- scope can only come from the project the
    instance was constructed with (`from_project_context`/`from_project`)."""
    import inspect

    from app.services.graph_access import GraphAccessService

    for name, member in inspect.getmembers(GraphAccessService, predicate=inspect.isfunction):
        if name.startswith("from_"):
            continue
        params = set(inspect.signature(member).parameters)
        assert "project_id" not in params, f"{name} must not accept a project_id parameter"
