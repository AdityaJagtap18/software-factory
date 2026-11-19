import pytest
from starlette.websockets import WebSocketDisconnect


def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


def _project(client, headers, name="Acme"):
    org = client.post("/api/v1/organizations", json={"name": name}, headers=headers).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=headers
    ).json()
    return org, project


def test_presence_rejects_invalid_token(client):
    alice_token, alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    # The server closes immediately with a custom code; starlette's test
    # client raises on the real close frame as soon as the connection is
    # opened, before any message is ever received.
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/v1/projects/{project['id']}/presence/ws?token=not-a-real-token"
        ):
            pass


def test_presence_rejects_user_with_no_project_access(client):
    alice_token, alice = _register_and_login(client, "alice@example.com", "Alice")
    bob_token, bob = _register_and_login(client, "bob@example.com", "Bob")
    _org, project = _project(client, alice)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/v1/projects/{project['id']}/presence/ws?token={bob_token}"
        ):
            pass


def test_single_viewer_sees_themselves_join(client):
    alice_token, alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    with client.websocket_connect(
        f"/api/v1/projects/{project['id']}/presence/ws?token={alice_token}"
    ) as ws:
        payload = ws.receive_json()
        assert len(payload["viewers"]) == 1
        assert payload["viewers"][0]["full_name"] == "Alice"


def test_second_viewer_triggers_a_real_broadcast_to_the_first(client):
    """Proves this is a genuine server-side broadcast across two real
    WebSocket connections, not a per-connection local count."""
    alice_token, alice = _register_and_login(client, "alice@example.com", "Alice")
    bob_token, bob = _register_and_login(client, "bob@example.com", "Bob")
    org, project = _project(client, alice)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=alice,
    )
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "bob@example.com", "role": "developer"},
        headers=alice,
    )

    with client.websocket_connect(
        f"/api/v1/projects/{project['id']}/presence/ws?token={alice_token}"
    ) as alice_ws:
        first = alice_ws.receive_json()
        assert len(first["viewers"]) == 1

        with client.websocket_connect(
            f"/api/v1/projects/{project['id']}/presence/ws?token={bob_token}"
        ) as bob_ws:
            bob_ws.receive_json()  # bob's own join snapshot

            # Alice's socket receives a second, real server-pushed message
            # the instant Bob's connection joins.
            updated = alice_ws.receive_json()
            names = {v["full_name"] for v in updated["viewers"]}
            assert names == {"Alice", "Bob"}

        # Bob's socket closing triggers a real broadcast removing him.
        after_leave = alice_ws.receive_json()
        assert {v["full_name"] for v in after_leave["viewers"]} == {"Alice"}
