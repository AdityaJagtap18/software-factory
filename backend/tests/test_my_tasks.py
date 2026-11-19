def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_my_tasks_aggregates_real_tasks_across_my_projects(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    project_a = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=alice
    ).json()
    project_b = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "NEXORA"}, headers=alice
    ).json()
    client.post(f"/api/v1/projects/{project_a['id']}/tasks", json={"title": "Task A"}, headers=alice)
    client.post(f"/api/v1/projects/{project_b['id']}/tasks", json={"title": "Task B"}, headers=alice)

    r = client.get("/api/v1/tasks/mine", headers=alice)
    assert r.status_code == 200
    tasks = r.json()
    assert len(tasks) == 2
    titles_by_project = {t["title"]: t["project_name"] for t in tasks}
    assert titles_by_project["Task A"] == "FINTRIX"
    assert titles_by_project["Task B"] == "NEXORA"


def test_my_tasks_is_genuinely_empty_for_a_user_with_no_access(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=alice
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/tasks", json={"title": "Task A"}, headers=alice)

    r = client.get("/api/v1/tasks/mine", headers=bob)
    assert r.status_code == 200
    assert r.json() == []


def test_my_tasks_requires_authentication(client):
    r = client.get("/api/v1/tasks/mine")
    assert r.status_code == 401
