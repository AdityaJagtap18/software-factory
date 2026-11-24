import subprocess

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


def test_scan_directory_extracts_python_imports(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "utils.py").write_text("def helper():\n    pass\n")
    (tmp_path / "pkg" / "service.py").write_text(
        "import os\nfrom . import utils\nfrom .utils import helper\n\n\ndef run():\n    pass\n"
    )

    files = code_ingestion.scan_directory(tmp_path)
    by_path = {f.relative_path: f for f in files}
    service = by_path["pkg/service.py"]

    modules = {(imp.module, imp.relative) for imp in service.imports}
    assert ("os", False) in modules
    assert (".utils", True) in modules
    assert (".utils", True) in modules  # from . import utils also resolves to ".utils"


def test_scan_directory_extracts_typescript_imports(tmp_path):
    (tmp_path / "foo.ts").write_text("export function foo() {}\n")
    (tmp_path / "bar.ts").write_text(
        "import { foo } from './foo';\nimport React from 'react';\n\nexport function bar() {}\n"
    )

    files = code_ingestion.scan_directory(tmp_path)
    by_path = {f.relative_path: f for f in files}
    bar = by_path["bar.ts"]

    modules = {(imp.module, imp.relative) for imp in bar.imports}
    assert ("./foo", True) in modules
    assert ("react", False) in modules


def test_detect_test_file_naming_conventions():
    assert code_ingestion._detect_test_file("test_math_utils.py") == (True, "math_utils.py")
    assert code_ingestion._detect_test_file("math_utils_test.py") == (True, "math_utils.py")
    assert code_ingestion._detect_test_file("foo.spec.ts") == (True, "foo")
    assert code_ingestion._detect_test_file("foo.test.tsx") == (True, "foo")
    assert code_ingestion._detect_test_file("math_utils.py") == (False, None)


def test_compute_relationships_resolves_python_depends_on_and_tests(tmp_path):
    (tmp_path / "math_utils.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "service.py").write_text("from . import math_utils\n\n\ndef run():\n    pass\n")
    (tmp_path / "test_math_utils.py").write_text(
        "from . import math_utils\n\n\ndef test_add():\n    pass\n"
    )

    files = code_ingestion.scan_directory(tmp_path)
    relationships = code_ingestion.compute_relationships(files)

    assert ("service.py", "math_utils.py") in relationships.depends_on
    assert ("test_math_utils.py", "math_utils.py") in relationships.depends_on
    assert ("test_math_utils.py", "math_utils.py") in relationships.tests


def test_compute_relationships_resolves_typescript_depends_on(tmp_path):
    (tmp_path / "utils.ts").write_text("export function helper() {}\n")
    (tmp_path / "service.ts").write_text(
        "import { helper } from './utils';\n\nexport function run() {}\n"
    )

    files = code_ingestion.scan_directory(tmp_path)
    relationships = code_ingestion.compute_relationships(files)

    assert ("service.ts", "utils.ts") in relationships.depends_on


def test_compute_relationships_ignores_external_imports(tmp_path):
    (tmp_path / "service.py").write_text("import os\nimport requests\n\n\ndef run():\n    pass\n")

    files = code_ingestion.scan_directory(tmp_path)
    relationships = code_ingestion.compute_relationships(files)

    assert relationships.depends_on == []


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
def test_ingest_repository_records_real_commit_sha(client, tmp_path):
    """P3-2: the Repository node's commit_sha must be the real `git rev-parse
    HEAD` of the ingested checkout -- never fabricated or left blank when the
    directory genuinely is a git repo."""
    (tmp_path / "math_utils.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "."],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    expected_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(tmp_path), check=True, capture_output=True, text=True
    ).stdout.strip()

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
    assert body["commit_sha"] == expected_sha
    assert body["commit_sha"] != ""


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


@requires_neo4j
def test_ingest_repository_records_depends_on_and_tests_relationships(client, tmp_path):
    """P3-3: imports resolvable to a same-repo file become a real
    File-DEPENDS_ON->File edge, and a recognized test file's naming
    convention becomes a real File-TESTS->File edge -- both readable back
    from the repository knowledge-graph endpoint, not just computed and
    discarded."""
    (tmp_path / "math_utils.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "service.py").write_text(
        "from . import math_utils\n\n\ndef run():\n    return math_utils.add(1, 2)\n"
    )
    (tmp_path / "test_math_utils.py").write_text(
        "from . import math_utils\n\n\ndef test_add():\n    assert math_utils.add(1, 2) == 3\n"
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    _org, project = _project(client, alice)

    r = client.post(
        f"/api/v1/projects/{project['id']}/knowledge/ingest-repository",
        json={"path": str(tmp_path)},
        headers=alice,
    )
    assert r.status_code == 200, r.text
    assert r.json()["connected"] is True

    graph = client.get(
        f"/api/v1/projects/{project['id']}/knowledge/graph",
        params={"graph_type": "repository"},
        headers=alice,
    ).json()
    assert graph["connected"] is True

    edges = {(e["source"], e["target"], e["type"]) for e in graph["edges"]}
    assert ("service.py", "math_utils.py", "DEPENDS_ON") in edges
    assert ("test_math_utils.py", "math_utils.py", "DEPENDS_ON") in edges
    assert ("test_math_utils.py", "math_utils.py", "TESTS") in edges


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
