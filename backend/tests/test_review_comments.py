def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _project_and_task(client, headers, name="Acme"):
    org = client.post("/api/v1/organizations", json={"name": name}, headers=headers).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=headers
    ).json()
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Add a feature"}, headers=headers
    ).json()
    return org, project, task


def test_create_and_list_review_comments(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project, task = _project_and_task(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/review-comments",
        json={"body": "This could use a null check", "file_path": "app/foo.py", "line_number": 42},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    comment = r.json()
    assert comment["resolved"] is False
    assert comment["file_path"] == "app/foo.py"
    assert comment["line_number"] == 42

    listed = client.get(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/review-comments", headers=alice
    ).json()
    assert len(listed) == 1
    assert listed[0]["id"] == comment["id"]


def test_resolve_review_comment(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project, task = _project_and_task(client, alice)
    comment = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/review-comments",
        json={"body": "General comment"},
        headers=alice,
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/review-comments/{comment['id']}/resolve",
        headers=alice,
    )
    assert r.status_code == 200, r.text
    assert r.json()["resolved"] is True


def test_viewer_can_comment_but_not_resolve(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org, project, task = _project_and_task(client, alice)
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
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/review-comments",
        json={"body": "Viewer feedback"},
        headers=bob,
    )
    assert r.status_code == 201, r.text
    comment = r.json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/review-comments/{comment['id']}/resolve",
        headers=bob,
    )
    assert r.status_code == 403


def test_review_comment_requires_nonempty_body(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project, task = _project_and_task(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task['id']}/review-comments",
        json={"body": ""},
        headers=alice,
    )
    assert r.status_code == 422
