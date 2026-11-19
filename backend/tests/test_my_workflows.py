def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_my_workflows_aggregates_real_workflows_across_my_projects(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    project_a = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=alice
    ).json()
    project_b = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "NEXORA"}, headers=alice
    ).json()
    client.post(
        f"/api/v1/projects/{project_a['id']}/workflows",
        json={"name": "Ship A", "steps": [{"title": "Step one"}]},
        headers=alice,
    )
    client.post(
        f"/api/v1/projects/{project_b['id']}/workflows",
        json={"name": "Ship B", "steps": [{"title": "Step one"}, {"title": "Step two"}]},
        headers=alice,
    )

    r = client.get("/api/v1/workflows/mine", headers=alice)
    assert r.status_code == 200
    workflows = r.json()
    assert len(workflows) == 2
    by_name = {w["name"]: w for w in workflows}
    assert by_name["Ship A"]["project_name"] == "FINTRIX"
    assert by_name["Ship B"]["project_name"] == "NEXORA"
    assert len(by_name["Ship B"]["steps"]) == 2


def test_my_workflows_is_genuinely_empty_for_a_user_with_no_access(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=alice
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/workflows",
        json={"name": "Ship it", "steps": [{"title": "Step one"}]},
        headers=alice,
    )

    r = client.get("/api/v1/workflows/mine", headers=bob)
    assert r.status_code == 200
    assert r.json() == []


def test_my_workflows_requires_authentication(client):
    r = client.get("/api/v1/workflows/mine")
    assert r.status_code == 401
