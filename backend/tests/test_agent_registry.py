from app.models.agent import Agent, AgentStatus
from app.services.agent_registry import sync_agent_registry
from app.services.agent_runtime.registry import all_adapters


def _register_and_login(client, email="alice@example.com", name="Alice"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_sync_creates_one_agent_row_per_real_adapter(client):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        sync_agent_registry(db)
        slugs = {a.slug for a in db.query(Agent).all()}
        assert slugs == {a.slug for a in all_adapters()}
    finally:
        db.close()


def test_sync_is_idempotent(client):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        sync_agent_registry(db)
        count_1 = db.query(Agent).count()
        sync_agent_registry(db)
        count_2 = db.query(Agent).count()
        assert count_1 == count_2
    finally:
        db.close()


def test_sync_deprecates_rather_than_deletes_a_removed_adapter():
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        ghost = Agent(slug="ghost_adapter", name="Ghost", version="0.0.1", capabilities=[])
        db.add(ghost)
        db.commit()

        sync_agent_registry(db)

        refreshed = db.query(Agent).filter_by(slug="ghost_adapter").first()
        assert refreshed is not None
        assert refreshed.status == AgentStatus.DEPRECATED
    finally:
        db.close()


def test_list_agents_endpoint_requires_auth(client):
    r = client.get("/api/v1/agents")
    assert r.status_code == 401


def test_list_agents_endpoint_returns_real_catalog(client):
    alice = _register_and_login(client)
    r = client.get("/api/v1/agents", headers=alice)
    assert r.status_code == 200
    body = r.json()
    slugs = {a["slug"] for a in body}
    assert slugs == {a.slug for a in all_adapters()}
    for entry in body:
        assert entry["status"] == "active"
        assert isinstance(entry["capabilities"], list)
