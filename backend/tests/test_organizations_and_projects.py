def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_organization_makes_creator_admin(client):
    headers = _register_and_login(client, "alice@example.com", "Alice")
    r = client.post("/api/v1/organizations", json={"name": "FINTRIX Labs"}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "FINTRIX Labs"
    assert body["my_role"] == "org_admin"
    assert body["slug"] == "fintrix-labs"


def test_non_member_cannot_access_organization(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")

    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    r = client.get(f"/api/v1/organizations/{org['id']}", headers=bob)
    assert r.status_code == 403


def test_non_admin_cannot_invite_members(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    # Alice invites Bob as a plain member.
    r = client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=alice,
    )
    assert r.status_code == 201, r.text

    # Bob (non-admin) tries to invite someone else -> forbidden.
    _register_and_login(client, "carol@example.com", "Carol")
    r2 = client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "carol@example.com", "role": "member"},
        headers=bob,
    )
    assert r2.status_code == 403


def test_last_admin_cannot_be_demoted(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    members = client.get(f"/api/v1/organizations/{org['id']}/members", headers=alice).json()
    alice_member_id = members[0]["id"]

    r = client.patch(
        f"/api/v1/organizations/{org['id']}/members/{alice_member_id}",
        json={"role": "member"},
        headers=alice,
    )
    assert r.status_code == 400


def test_project_create_and_isolated_visibility(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=alice,
    )

    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "FINTRIX Platform", "description": "Invoice automation"},
        headers=alice,
    ).json()
    assert project["my_role"] == "project_admin"

    # Bob is an org member but not an explicit project member and not org_admin ->
    # per our access model he has no project access until added.
    r = client.get(f"/api/v1/projects/{project['id']}", headers=bob)
    assert r.status_code == 403

    # Alice adds Bob as a developer on the project.
    r2 = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "bob@example.com", "role": "developer"},
        headers=alice,
    )
    assert r2.status_code == 201

    r3 = client.get(f"/api/v1/projects/{project['id']}", headers=bob)
    assert r3.status_code == 200
    assert r3.json()["my_role"] == "developer"


def test_developer_cannot_update_project(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=alice,
    )
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "Core"}, headers=alice
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "bob@example.com", "role": "developer"},
        headers=alice,
    )

    r = client.patch(
        f"/api/v1/projects/{project['id']}", json={"name": "Renamed"}, headers=bob
    )
    assert r.status_code == 403


def test_cross_organization_isolation(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")

    org_a = client.post("/api/v1/organizations", json={"name": "Org A"}, headers=alice).json()
    project_a = client.post(
        f"/api/v1/organizations/{org_a['id']}/projects", json={"name": "Secret Project"}, headers=alice
    ).json()

    # Bob has never been a member of Org A and cannot reach its project by id.
    r = client.get(f"/api/v1/projects/{project_a['id']}", headers=bob)
    assert r.status_code == 403

    r2 = client.get(f"/api/v1/organizations/{org_a['id']}/projects", headers=bob)
    assert r2.status_code == 403
