def register(client, email="alice@example.com", password="password123", full_name="Alice Admin"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )


def login(client, email="alice@example.com", password="password123"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_register_and_login(client):
    r = register(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert "hashed_password" not in body

    r2 = login(client)
    assert r2.status_code == 200, r2.text
    tokens = r2.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]


def test_duplicate_register_rejected(client):
    register(client)
    r = register(client)
    assert r.status_code == 409


def test_login_wrong_password_rejected(client):
    register(client)
    r = login(client, password="wrong-password")
    assert r.status_code == 401


def test_me_requires_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_with_valid_token(client):
    register(client)
    tokens = login(client).json()
    r = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"


def test_refresh_rotates_token(client):
    register(client)
    tokens = login(client).json()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # old refresh token must now be rejected (rotation/revocation)
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401


def test_logout_revokes_refresh_token(client):
    register(client)
    tokens = login(client).json()
    r = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 204
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401
