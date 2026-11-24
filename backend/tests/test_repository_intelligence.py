import json
from pathlib import Path
import tempfile
import uuid
import pytest

from app.models.git_integration import GitInstallation, GitProvider, InstallationStatus, RepositoryConnection, RepositoryConnectionStatus
from app.models.project import Project, ProjectRole
from app.models.user import User
from app.services import knowledge_graph
from app.services.graphify_adapter import (
    ManifestDependency,
    NormalizedEdge,
    NormalizedNode,
    extract_manifest_dependencies,
    run_graphify_extraction,
)
from app.services import repository_intelligence_service as ris
from tests.conftest import TestingSessionLocal


@pytest.fixture
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()



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


def _setup_project_with_repo(client, headers, db_session, user_email="test_intel@example.com"):
    org = client.post("/api/v1/organizations", json={"name": "Acme Org"}, headers=headers).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "Repo Intel Proj"}, headers=headers
    ).json()

    user = db_session.query(User).filter_by(email=user_email).first()

    # Create GitInstallation and RepositoryConnection
    inst = GitInstallation(
        organization_id=uuid.UUID(org["id"]),
        provider=GitProvider.GITHUB,
        external_installation_id="12345",
        account_login="acme",
        status=InstallationStatus.CONNECTED,
        created_by_user_id=user.id,
    )
    db_session.add(inst)
    db_session.flush()

    repo = RepositoryConnection(
        project_id=uuid.UUID(project["id"]),
        git_installation_id=inst.id,
        owner="acme",
        name="test-repo",
        full_name="acme/test-repo",
        default_branch="main",
        status=RepositoryConnectionStatus.CONNECTED,
        created_by_user_id=user.id,
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    return org, project, repo


def test_manifest_dependencies_extraction():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Create package.json
        pkg_json = tmp_path / "package.json"
        pkg_json.write_text(json.dumps({
            "dependencies": {"express": "^4.18.2", "lodash": "4.17.21"},
            "devDependencies": {"typescript": "^5.0.0"}
        }))

        # Create requirements.txt
        req_txt = tmp_path / "requirements.txt"
        req_txt.write_text("fastapi>=0.100.0\nuvicorn==0.23.2\n# comment\n")

        deps = extract_manifest_dependencies(tmp_path)
        dep_names = {d.name for d in deps}
        assert "express" in dep_names
        assert "lodash" in dep_names
        assert "typescript" in dep_names
        assert "fastapi" in dep_names
        assert "uvicorn" in dep_names


def test_graphify_extraction_on_directory():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Create sample Python source files
        src = tmp_path / "src"
        src.mkdir()
        (src / "service.py").write_text("class Calculator:\n    def add(self, a, b):\n        return a + b\n")
        (src / "test_service.py").write_text("def test_add():\n    pass\n")

        result = run_graphify_extraction(tmp_path)
        assert result.total_files >= 2
        assert result.lines_of_code > 0
        assert "Python" in result.languages
        types = {n.type for n in result.nodes}
        assert "File" in types
        assert "Test" in types


def test_repository_settings_api(client, db_session):
    alice = _register_and_login(client, "test_intel@example.com", "Alice Intel")
    _org, project, repo = _setup_project_with_repo(client, alice, db_session)

    # Get settings (should auto-create defaults)
    res = client.get(
        f"/api/v1/projects/{project['id']}/repository-intelligence/settings?repository_id={repo.id}",
        headers=alice,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["default_branch"] == "main"
    assert body["auto_index_on_sync"] is True
    assert "node_modules" in body["excluded_paths"]

    # Update settings
    update_res = client.put(
        f"/api/v1/projects/{project['id']}/repository-intelligence/settings",
        json={
            "repository_connection_id": str(repo.id),
            "default_branch": "develop",
            "max_file_size_kb": 1024,
            "auto_index_on_sync": False,
        },
        headers=alice,
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["default_branch"] == "develop"
    assert updated["max_file_size_kb"] == 1024
    assert updated["auto_index_on_sync"] is False


def test_repository_branches_api(client, db_session):
    email = "test_branches@example.com"
    alice = _register_and_login(client, email, "Bob Branches")
    _org, project, repo = _setup_project_with_repo(client, alice, db_session, user_email=email)

    res = client.get(
        f"/api/v1/projects/{project['id']}/repository-intelligence/repositories/{repo.id}/branches",
        headers=alice,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["repository_id"] == str(repo.id)
    assert len(body["branches"]) >= 1
    assert any(b["name"] == "main" and b["is_default"] for b in body["branches"])


@requires_neo4j
def test_indexing_pipeline_and_intelligence_endpoints(client, db_session, monkeypatch):
    email = "test_full@example.com"
    alice = _register_and_login(client, email, "Full Intel")
    _org, project, repo = _setup_project_with_repo(client, alice, db_session, user_email=email)

    # Mock checkout to point to a temporary test directory with code
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        src = tmp_path / "app"
        src.mkdir()
        (src / "main.py").write_text("import utils\n\ndef run():\n    return utils.helper()\n")
        (src / "utils.py").write_text("def helper():\n    return 42\n")
        (src / "test_main.py").write_text("import main\n\ndef test_run():\n    assert main.run() == 42\n")

        monkeypatch.setattr(
            "app.services.repository_intelligence_service._sync_connected_repo_checkout",
            lambda _rc: tmp_path,
        )

        # 1. Trigger Indexing
        idx_res = client.post(
            f"/api/v1/projects/{project['id']}/repository-intelligence/index",
            json={"repository_id": str(repo.id), "branch": "main"},
            headers=alice,
        )
        assert idx_res.status_code == 200
        run_data = idx_res.json()
        assert run_data["status"] == "COMPLETED"

        # 2. Get Overview
        overview_res = client.get(
            f"/api/v1/projects/{project['id']}/repository-intelligence/overview?repository_id={repo.id}&branch=main",
            headers=alice,
        )
        assert overview_res.status_code == 200
        overview = overview_res.json()
        assert overview["index_status"]["status"] == "COMPLETED"
        assert overview["metrics"]["total_files"] >= 3

        # 3. Get Graph
        graph_res = client.get(
            f"/api/v1/projects/{project['id']}/repository-intelligence/graph?repository_id={repo.id}&branch=main",
            headers=alice,
        )
        assert graph_res.status_code == 200
        graph = graph_res.json()
        assert len(graph["nodes"]) > 0
        assert "communities" in graph
        assert len(graph["communities"]) > 0
        first_comm = graph["communities"][0]
        assert "name" in first_comm
        assert "color" in first_comm
        assert first_comm["node_count"] > 0
        first_node = graph["nodes"][0]
        assert "community_id" in first_node
        assert "degree" in first_node

        # 4. Search Code
        search_res = client.get(
            f"/api/v1/projects/{project['id']}/repository-intelligence/search?repository_id={repo.id}&branch=main&q=helper",
            headers=alice,
        )
        assert search_res.status_code == 200
        search = search_res.json()
        assert search["total"] >= 1

        # 5. Dependencies
        dep_res = client.get(
            f"/api/v1/projects/{project['id']}/repository-intelligence/dependencies?repository_id={repo.id}&branch=main",
            headers=alice,
        )
        assert dep_res.status_code == 200

        # 6. History
        hist_res = client.get(
            f"/api/v1/projects/{project['id']}/repository-intelligence/history?repository_id={repo.id}",
            headers=alice,
        )
        assert hist_res.status_code == 200
        history = hist_res.json()
        assert len(history["runs"]) >= 1

        # 7. Node Details and Neighbors
        if graph["nodes"]:
            first_node_id = graph["nodes"][0]["id"]
            node_res = client.get(
                f"/api/v1/projects/{project['id']}/repository-intelligence/graph/nodes/{first_node_id}?repository_id={repo.id}&branch=main",
                headers=alice,
            )
            assert node_res.status_code == 200
            node_detail = node_res.json()
            assert "node" in node_detail
            assert "incoming" in node_detail
            assert "outgoing" in node_detail

            neighbors_res = client.get(
                f"/api/v1/projects/{project['id']}/repository-intelligence/graph/nodes/{first_node_id}/neighbors?repository_id={repo.id}&branch=main",
                headers=alice,
            )
            assert neighbors_res.status_code == 200
            neighbors = neighbors_res.json()
            assert "center_node_id" in neighbors

            # 8. Impact Analysis
            impact_res = client.get(
                f"/api/v1/projects/{project['id']}/repository-intelligence/impact/{first_node_id}?repository_id={repo.id}&branch=main",
                headers=alice,
            )
            assert impact_res.status_code == 200
            impact = impact_res.json()
            assert "target_node" in impact
            assert "confidence" in impact

