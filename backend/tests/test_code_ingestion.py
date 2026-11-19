import pytest

from app.services import code_ingestion, knowledge_graph


def _neo4j_available() -> bool:
    ok, _detail = knowledge_graph.health_check()
    return ok


requires_neo4j = pytest.mark.skipif(
    not _neo4j_available(), reason="Neo4j is not reachable in this environment"
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


def test_scan_directory_parses_real_python_and_typescript_symbols(tmp_path):
    (tmp_path / "service.py").write_text(
        "class Widget:\n    def spin(self):\n        pass\n\n\ndef top_level():\n    pass\n"
    )
    (tmp_path / "component.ts").write_text(
        "export class WidgetComponent {\n}\n\nexport function helper() {\n}\n"
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("def should_not_appear():\n    pass\n")

    files = code_ingestion.scan_directory(tmp_path)
    by_path = {f.relative_path: f for f in files}

    assert "service.py" in by_path
    assert "component.ts" in by_path
    assert "node_modules/ignored.py" not in by_path

    py_symbols = {(s.name, s.kind) for s in by_path["service.py"].symbols}
    assert ("Widget", "class") in py_symbols
    assert ("spin", "function") in py_symbols
    assert ("top_level", "function") in py_symbols

    ts_symbols = {(s.name, s.kind) for s in by_path["component.ts"].symbols}
    assert ("WidgetComponent", "class") in ts_symbols
    assert ("helper", "function") in ts_symbols


def test_scan_directory_raises_on_missing_path(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(code_ingestion.IngestionError):
        code_ingestion.scan_directory(missing)


@requires_neo4j
def test_ingest_repository_round_trip(client, tmp_path):
    """Proves ingestion writes real File/Function/Class nodes from a real
    directory on disk, and the code-graph endpoint reads them back."""
    (tmp_path / "math_utils.py").write_text("def add(a, b):\n    return a + b\n")

    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/knowledge/ingest-repository",
        json={"path": str(tmp_path)},
        headers=alice,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is True
    assert body["files_scanned"] == 1
    assert body["symbols_found"] == 1

    graph = client.get(
        f"/api/v1/projects/{project['id']}/knowledge/code-graph", headers=alice
    ).json()
    assert graph["connected"] is True
    files = {f["path"]: f for f in graph["files"]}
    assert "math_utils.py" in files
    assert files["math_utils.py"]["symbols"][0]["name"] == "add"


@requires_neo4j
def test_ingest_repository_rejects_nonexistent_path(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/knowledge/ingest-repository",
        json={"path": "/this/path/genuinely/does/not/exist"},
        headers=alice,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert "does not exist" in body["detail"]


def test_non_admin_cannot_ingest_repository(client, tmp_path):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
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

    r = client.post(
        f"/api/v1/projects/{project['id']}/knowledge/ingest-repository",
        json={"path": str(tmp_path)},
        headers=bob,
    )
    assert r.status_code == 403
