def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_creating_an_org_produces_a_real_audit_log_entry_readable_via_the_new_endpoint(client):
    """P6-2: the already-real `AuditLog` write path (organizations.py calls
    `audit.record` on org creation) now has a real read surface -- the
    audit trail had zero API/frontend consumer before this phase."""
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    r = client.get(f"/api/v1/organizations/{org['id']}/audit-logs", headers=alice)
    assert r.status_code == 200, r.text
    entries = r.json()
    assert len(entries) >= 1
    assert any(e["action"] == "organization.create" for e in entries)


def test_audit_log_filters_by_action(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    r = client.get(
        f"/api/v1/organizations/{org['id']}/audit-logs",
        params={"action": "organization.create"},
        headers=alice,
    )
    assert r.status_code == 200
    entries = r.json()
    assert all(e["action"] == "organization.create" for e in entries)
    assert len(entries) == 1


def test_non_member_cannot_read_audit_log(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org = client.post("/api/v1/organizations", json={"name": "Acme"}, headers=alice).json()

    r = client.get(f"/api/v1/organizations/{org['id']}/audit-logs", headers=bob)
    assert r.status_code == 403
