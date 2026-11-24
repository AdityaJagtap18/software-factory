import pytest

from app.services import embeddings


def _embeddings_available() -> bool:
    try:
        vec = embeddings.embed_text("probe")
        return len(vec) == 768
    except embeddings.EmbeddingError:
        return False


requires_embeddings = pytest.mark.skipif(
    not _embeddings_available(), reason="Local embedding model (Ollama nomic-embed-text) is not reachable"
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


@requires_embeddings
def test_create_document_produces_real_chunks_and_embeddings(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/documents",
        json={
            "title": "Deployment Runbook",
            "content": "To deploy the service, first run the database migrations. "
            "Then restart the backend workers. Finally verify the health endpoint.",
        },
        headers=alice,
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["chunk_count"] >= 1
    assert doc["title"] == "Deployment Runbook"

    chunks = client.get(f"/api/v1/projects/{project['id']}/documents/{doc['id']}", headers=alice).json()
    assert len(chunks) == doc["chunk_count"]
    assert "migrations" in chunks[0]["content"] or "restart" in chunks[0]["content"]


@requires_embeddings
def test_search_documents_returns_the_relevant_chunk_with_a_real_score(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    client.post(
        f"/api/v1/projects/{project['id']}/documents",
        json={
            "title": "Database Notes",
            "content": "The production database uses PostgreSQL with pgvector for embeddings.",
        },
        headers=alice,
    )
    client.post(
        f"/api/v1/projects/{project['id']}/documents",
        json={
            "title": "Unrelated Notes",
            "content": "The office coffee machine is on the third floor near the elevators.",
        },
        headers=alice,
    )

    r = client.post(
        f"/api/v1/projects/{project['id']}/documents/search",
        json={"query": "What database does production use?", "top_k": 3},
        headers=alice,
    )
    assert r.status_code == 200, r.text
    results = r.json()
    assert len(results) >= 1
    assert results[0]["document_title"] == "Database Notes"
    assert 0.0 <= results[0]["score"] <= 1.0


def test_search_with_no_documents_returns_empty_not_an_error(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/documents/search",
        json={"query": "anything"},
        headers=alice,
    )
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_create_document_rejects_empty_content(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/documents",
        json={"title": "Empty", "content": "   "},
        headers=alice,
    )
    assert r.status_code == 400


@requires_embeddings
def test_delete_document_removes_its_chunks(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)
    doc = client.post(
        f"/api/v1/projects/{project['id']}/documents",
        json={"title": "Temp", "content": "This document will be deleted shortly after creation."},
        headers=alice,
    ).json()

    r = client.delete(f"/api/v1/projects/{project['id']}/documents/{doc['id']}", headers=alice)
    assert r.status_code == 204

    listed = client.get(f"/api/v1/projects/{project['id']}/documents", headers=alice).json()
    assert listed == []


def test_cross_project_access_is_rejected(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    _org, project = _project(client, alice)

    r = client.get(f"/api/v1/projects/{project['id']}/documents", headers=bob)
    assert r.status_code in (403, 404)
