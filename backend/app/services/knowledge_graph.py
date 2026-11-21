"""Syncs a project's real tasks, workflows, repositories, and coding-agent connections
into Neo4j as a genuine graph of what actually happened in the factory —
never a fabricated entity/relationship count. If Neo4j is unreachable,
every call here honestly reports `connected: False` with the real driver
error; it never returns a fake empty-but-successful graph.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
import os
from pathlib import Path
import subprocess
import uuid

import neo4j
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models.agent_runtime import CodingAgentConnection
from app.models.git_integration import RepositoryConnection, RepositoryConnectionStatus
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow import Workflow
from app.services import code_ingestion
from app.services.git_provider.registry import get_git_provider


@lru_cache
def _driver() -> neo4j.Driver:
    settings = get_settings()
    return neo4j.GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )


def health_check() -> tuple[bool, str]:
    try:
        with _driver().session() as session:
            session.run("RETURN 1").single()
        return True, "Connected"
    except Exception as exc:  # noqa: BLE001 - surface the real driver error, never fake one
        return False, str(exc)


def ensure_schema() -> None:
    """Idempotent schema setup (P2-2 of the engineering audit's remaining
    roadmap). Safe to call repeatedly (every call site already does, before
    every sync/ingest) and safe to call at app startup. Covers every node
    label actually written by this module today -- both the
    platform-entity mirror (Project/Repository/User/Task/Workflow/
    Connection) and the code-structure slice (File/Directory/Class/
    Function/Module), which previously had no constraints or indexes at
    all despite being the highest-cardinality, most heavily MERGE'd labels
    in the graph (`04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` S3.1)."""
    ok, _ = health_check()
    if not ok:
        return
    try:
        with _driver().session() as session:
            # Uniqueness constraints (also create a backing index) for
            # every label addressed by a single Postgres-mirrored id.
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Project) REQUIRE p.id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (r:Repository) REQUIRE r.id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (t:Task) REQUIRE t.id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (w:Workflow) REQUIRE w.id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Connection) REQUIRE c.id IS UNIQUE")
            # Code-structure labels are addressed by a composite
            # (project_id, path[, name, line]) key, not a single id -- a
            # composite uniqueness constraint (also Neo4j-5 compatible)
            # plus a project_id range index, since every query here filters
            # on project_id first.
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (f:File) "
                "REQUIRE (f.project_id, f.path) IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Directory) "
                "REQUIRE (d.project_id, d.path) IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Module) "
                "REQUIRE (m.project_id, m.name) IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Class) "
                "REQUIRE (c.project_id, c.path, c.name, c.line) IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (fn:Function) "
                "REQUIRE (fn.project_id, fn.path, fn.name, fn.line) IS UNIQUE"
            )
            session.run("CREATE INDEX IF NOT EXISTS FOR (f:File) ON (f.project_id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (c:Class) ON (c.project_id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (fn:Function) ON (fn.project_id)")
    except Exception:  # noqa: BLE001
        pass


@dataclass
class GraphNode:
    id: str
    type: str
    label: str
    properties: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    type: str


@dataclass
class SyncResult:
    connected: bool
    detail: str
    nodes_synced: int = 0
    relationships_synced: int = 0
    synced_at: datetime | None = None


@dataclass
class GraphResult:
    connected: bool
    detail: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


@dataclass
class IngestResult:
    connected: bool
    detail: str
    files_scanned: int = 0
    symbols_found: int = 0
    nodes_synced: int = 0
    relationships_synced: int = 0
    synced_at: datetime | None = None
    commit_sha: str = ""


def sync_project(db: DBSession, project: Project) -> SyncResult:
    ok, detail = health_check()
    if not ok:
        return SyncResult(connected=False, detail=detail)

    ensure_schema()

    tasks = db.query(Task).filter_by(project_id=project.id).all()
    workflows = db.query(Workflow).filter_by(project_id=project.id).all()
    repos = db.query(RepositoryConnection).filter_by(project_id=project.id).all()
    connection_ids = {t.coding_agent_connection_id for t in tasks if t.coding_agent_connection_id}
    connections = (
        db.query(CodingAgentConnection).filter(CodingAgentConnection.id.in_(connection_ids)).all()
        if connection_ids
        else []
    )
    creator_ids = {t.created_by_user_id for t in tasks} | {w.created_by_user_id for w in workflows}
    users = db.query(User).filter(User.id.in_(creator_ids)).all() if creator_ids else []

    synced_at = datetime.now(timezone.utc)
    nodes_synced = 0
    relationships_synced = 0

    with _driver().session() as session:
        session.run(
            """
            MERGE (p:Project {id: $id})
            SET p.name = $name, p.status = $status, p.synced_at = $synced_at
            """,
            id=str(project.id),
            name=project.name,
            status=project.status.value,
            synced_at=synced_at.isoformat(),
        )
        nodes_synced += 1

        for repo in repos:
            session.run(
                """
                MERGE (r:Repository {id: $id})
                SET r.full_name = $full_name,
                    r.owner = $owner,
                    r.name = $name,
                    r.default_branch = $default_branch,
                    r.status = $status,
                    r.project_id = $project_id
                WITH r
                MATCH (p:Project {id: $project_id})
                MERGE (p)-[:HAS_REPOSITORY]->(r)
                """,
                id=str(repo.id),
                full_name=repo.full_name,
                owner=repo.owner,
                name=repo.name,
                default_branch=repo.default_branch or "main",
                status=repo.status.value,
                project_id=str(project.id),
            )
            nodes_synced += 1
            relationships_synced += 1

        for user in users:
            session.run(
                "MERGE (u:User {id: $id}) SET u.full_name = $full_name",
                id=str(user.id),
                full_name=user.full_name,
            )
            nodes_synced += 1

        for connection in connections:
            session.run(
                """
                MERGE (c:Connection {id: $id})
                SET c.runtime_slug = $runtime_slug, c.status = $status
                """,
                id=str(connection.id),
                runtime_slug=connection.runtime_slug,
                status=connection.status.value,
            )
            nodes_synced += 1

        for workflow in workflows:
            session.run(
                """
                MERGE (w:Workflow {id: $id})
                SET w.name = $name, w.status = $status
                WITH w
                MATCH (p:Project {id: $project_id})
                MERGE (p)-[:HAS_WORKFLOW]->(w)
                """,
                id=str(workflow.id),
                name=workflow.name,
                status=workflow.status.value,
                project_id=str(project.id),
            )
            nodes_synced += 1
            relationships_synced += 1

            session.run(
                """
                MATCH (w:Workflow {id: $workflow_id}), (u:User {id: $user_id})
                MERGE (u)-[:CREATED]->(w)
                """,
                workflow_id=str(workflow.id),
                user_id=str(workflow.created_by_user_id),
            )
            relationships_synced += 1

        for task in tasks:
            session.run(
                """
                MERGE (t:Task {id: $id})
                SET t.title = $title, t.status = $status, t.priority = $priority
                WITH t
                MATCH (p:Project {id: $project_id})
                MERGE (p)-[:HAS_TASK]->(t)
                """,
                id=str(task.id),
                title=task.title,
                status=task.status.value,
                priority=task.priority.value,
                project_id=str(project.id),
            )
            nodes_synced += 1
            relationships_synced += 1

            session.run(
                """
                MATCH (t:Task {id: $task_id}), (u:User {id: $user_id})
                MERGE (u)-[:CREATED]->(t)
                """,
                task_id=str(task.id),
                user_id=str(task.created_by_user_id),
            )
            relationships_synced += 1

            if task.coding_agent_connection_id:
                session.run(
                    """
                    MATCH (t:Task {id: $task_id}), (c:Connection {id: $connection_id})
                    MERGE (t)-[:ASSIGNED_TO]->(c)
                    """,
                    task_id=str(task.id),
                    connection_id=str(task.coding_agent_connection_id),
                )
                relationships_synced += 1

            if task.git_branch_name and repos:
                for repo in repos:
                    session.run(
                        """
                        MATCH (t:Task {id: $task_id}), (r:Repository {id: $repo_id})
                        MERGE (t)-[:TARGETS_REPOSITORY]->(r)
                        """,
                        task_id=str(task.id),
                        repo_id=str(repo.id),
                    )
                    relationships_synced += 1

            if task.workflow_id:
                session.run(
                    """
                    MATCH (w:Workflow {id: $workflow_id}), (t:Task {id: $task_id})
                    MERGE (w)-[:HAS_STEP {order: $order}]->(t)
                    """,
                    workflow_id=str(task.workflow_id),
                    task_id=str(task.id),
                    order=task.step_order if task.step_order is not None else 0,
                )
                relationships_synced += 1

    return SyncResult(
        connected=True,
        detail="Synced",
        nodes_synced=nodes_synced,
        relationships_synced=relationships_synced,
        synced_at=synced_at,
    )


def _sync_connected_repo_checkout(rc: RepositoryConnection) -> Path:
    """Clones or pulls the real connected repository into a local cache directory
    for scanning and indexing."""
    from app.services.git_worktree import _GIT_TIMEOUT_SECONDS, _sanitize, _worktree_root

    adapter = get_git_provider(rc.installation.provider.value)
    if adapter is None:
        raise ValueError(f"Unknown git provider '{rc.installation.provider.value}'")

    clone_url = adapter.get_authenticated_clone_url(
        rc.installation.external_installation_id, rc.owner, rc.name
    )

    cache_root = _worktree_root() / "repo_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    repo_dir = cache_root / f"{rc.owner}_{rc.name}"
    branch = rc.default_branch or "main"
    secret = (
        adapter._mint_installation_token(rc.installation.external_installation_id)
        if hasattr(adapter, "_mint_installation_token")
        else ""
    )

    if not repo_dir.exists() or not (repo_dir / ".git").exists():
        if repo_dir.exists():
            import shutil
            shutil.rmtree(repo_dir, ignore_errors=True)
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", "-b", branch, clone_url, str(repo_dir)],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            raise RuntimeError(_sanitize(proc.stderr or proc.stdout or "git clone failed", secret))
    else:
        subprocess.run(
            ["git", "remote", "set-url", "origin", clone_url],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        proc = subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", branch],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if proc.returncode == 0:
            subprocess.run(
                ["git", "checkout", branch],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            subprocess.run(
                ["git", "reset", "--hard", f"origin/{branch}"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
    return repo_dir


def _git_head_sha(repo_dir: Path) -> str:
    """Real `git rev-parse HEAD` in `repo_dir` -- never fabricated. Returns
    "" if the directory isn't a real checkout or the command fails, so a
    caller can honestly record "unknown" rather than a guessed SHA (P3-2:
    commit-level provenance for what was actually ingested)."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def ingest_repository(
    project: Project,
    root_path: str = "",
    db: DBSession | None = None,
    repo_connection_id: uuid.UUID | None = None,
) -> IngestResult:
    """Parses source files from a real directory on disk or from the connected
    repository checkout, and upserts real File/Directory/Class/Function/Module
    nodes into Neo4j."""
    ok, detail = health_check()
    if not ok:
        return IngestResult(connected=False, detail=detail)

    ensure_schema()

    repo_conn = None
    if db is not None:
        if repo_connection_id:
            repo_conn = db.get(RepositoryConnection, repo_connection_id)
        else:
            repo_conn = (
                db.query(RepositoryConnection)
                .filter(
                    RepositoryConnection.project_id == project.id,
                    RepositoryConnection.status == RepositoryConnectionStatus.CONNECTED,
                )
                .first()
            )

    commit_sha = ""
    if not root_path:
        if repo_conn is None:
            return IngestResult(
                connected=False,
                detail="No connected repository found for this project. Connect a repository first or specify a path.",
            )
        try:
            repo_dir = _sync_connected_repo_checkout(repo_conn)
            root_path = str(repo_dir)
            commit_sha = _git_head_sha(repo_dir)
        except Exception as exc:  # noqa: BLE001
            return IngestResult(
                connected=False,
                detail=f"Could not retrieve repository checkout for '{repo_conn.full_name}': {exc}",
            )
    else:
        # An explicit local path was given directly (admin-supplied, not
        # necessarily a git checkout at all) -- still record a real SHA if
        # it happens to be one, rather than fabricating.
        commit_sha = _git_head_sha(Path(root_path))

    try:
        files = code_ingestion.scan_directory(Path(root_path))
    except code_ingestion.IngestionError as exc:
        return IngestResult(connected=False, detail=exc.message)

    synced_at = datetime.now(timezone.utc)
    nodes_synced = 0
    relationships_synced = 0
    symbols_found = sum(len(f.symbols) for f in files)

    with _driver().session() as session:
        # Drop this project's previous code-structure subgraph
        session.run(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_FILE]->(f:File)
            OPTIONAL MATCH (f)-[:DEFINES]->(s)
            OPTIONAL MATCH (f)-[:IMPORTS]->(m:Module)
            DETACH DELETE f, s, m
            """,
            project_id=str(project.id),
        )

        session.run(
            "MERGE (p:Project {id: $id}) SET p.name = $name",
            id=str(project.id),
            name=project.name,
        )

        repo_id = str(repo_conn.id) if repo_conn else f"repo_{project.id}"
        repo_name = repo_conn.full_name if repo_conn else project.name
        default_branch = (repo_conn.default_branch if repo_conn else "") or "main"

        session.run(
            """
            MATCH (p:Project {id: $project_id})
            MERGE (r:Repository {id: $repo_id})
            SET r.full_name = $full_name,
                r.project_id = $project_id,
                r.default_branch = $default_branch,
                r.synced_at = $synced_at,
                r.commit_sha = $commit_sha
            MERGE (p)-[:HAS_REPOSITORY]->(r)
            """,
            project_id=str(project.id),
            repo_id=repo_id,
            full_name=repo_name,
            default_branch=default_branch,
            commit_sha=commit_sha,
            synced_at=synced_at.isoformat(),
        )
        nodes_synced += 1
        relationships_synced += 1

        created_dirs: set[str] = set()

        for code_file in files:
            # Create directory hierarchy
            parts = code_file.relative_path.split("/")
            if len(parts) > 1:
                cur_dir = ""
                for part in parts[:-1]:
                    cur_dir = f"{cur_dir}/{part}" if cur_dir else part
                    if cur_dir not in created_dirs:
                        created_dirs.add(cur_dir)
                        session.run(
                            """
                            MATCH (r:Repository {id: $repo_id})
                            MERGE (d:Directory {project_id: $project_id, path: $path})
                            SET d.name = $name
                            MERGE (r)-[:CONTAINS]->(d)
                            """,
                            project_id=str(project.id),
                            repo_id=repo_id,
                            path=cur_dir,
                            name=part,
                        )
                        nodes_synced += 1
                        relationships_synced += 1

            session.run(
                """
                MATCH (p:Project {id: $project_id}), (r:Repository {id: $repo_id})
                MERGE (f:File {project_id: $project_id, path: $path})
                SET f.language = $language, f.repository_id = $repo_id
                MERGE (p)-[:HAS_FILE]->(f)
                MERGE (r)-[:HAS_FILE]->(f)
                """,
                project_id=str(project.id),
                repo_id=repo_id,
                path=code_file.relative_path,
                language=code_file.language,
            )
            nodes_synced += 1
            relationships_synced += 2

            for symbol in code_file.symbols:
                if symbol.kind == "import":
                    session.run(
                        """
                        MATCH (f:File {project_id: $project_id, path: $path})
                        MERGE (m:Module {project_id: $project_id, name: $name})
                        MERGE (f)-[:IMPORTS]->(m)
                        """,
                        project_id=str(project.id),
                        path=code_file.relative_path,
                        name=symbol.name,
                    )
                    nodes_synced += 1
                    relationships_synced += 1
                else:
                    label = "Class" if symbol.kind == "class" else "Function"
                    session.run(
                        f"""
                        MATCH (f:File {{project_id: $project_id, path: $path}})
                        MERGE (s:{label} {{project_id: $project_id, path: $path, name: $name, line: $line}})
                        MERGE (f)-[:DEFINES]->(s)
                        """,
                        project_id=str(project.id),
                        path=code_file.relative_path,
                        name=symbol.name,
                        line=symbol.line,
                    )
                    nodes_synced += 1
                    relationships_synced += 1

    return IngestResult(
        connected=True,
        detail=f"Ingested {len(files)} real source files from {root_path}",
        files_scanned=len(files),
        symbols_found=symbols_found,
        nodes_synced=nodes_synced,
        relationships_synced=relationships_synced,
        synced_at=synced_at,
        commit_sha=commit_sha,
    )


@dataclass
class CodeFileSummary:
    path: str
    language: str
    symbols: list[dict] = field(default_factory=list)


@dataclass
class CodeGraphResult:
    connected: bool
    detail: str
    files: list[CodeFileSummary] = field(default_factory=list)


def get_code_graph(project_id) -> CodeGraphResult:
    ok, detail = health_check()
    if not ok:
        return CodeGraphResult(connected=False, detail=detail)

    files: list[CodeFileSummary] = []
    with _driver().session() as session:
        records = session.run(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_FILE]->(f:File)
            OPTIONAL MATCH (f)-[:DEFINES]->(s)
            WITH f, collect(s) AS symbols
            RETURN f.path AS path, f.language AS language, symbols
            ORDER BY f.path
            """,
            project_id=str(project_id),
        )
        for record in records:
            symbols = [
                {"name": s["name"], "kind": list(s.labels)[0].lower(), "line": s["line"]}
                for s in record["symbols"]
                if s is not None
            ]
            files.append(
                CodeFileSummary(path=record["path"], language=record["language"], symbols=symbols)
            )

    return CodeGraphResult(connected=True, detail="OK", files=files)


def get_project_graph(project_id) -> GraphResult:
    ok, detail = health_check()
    if not ok:
        return GraphResult(connected=False, detail=detail)

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    with _driver().session() as session:
        node_records = session.run(
            """
            MATCH (p:Project {id: $project_id})
            OPTIONAL MATCH (p)-[:HAS_TASK|HAS_WORKFLOW|HAS_REPOSITORY]->(direct)
            OPTIONAL MATCH (direct)-[:ASSIGNED_TO|HAS_STEP|TARGETS_REPOSITORY]-(neighbor)
            OPTIONAL MATCH (creator:User)-[:CREATED]->(direct)
            WITH p, collect(DISTINCT direct) AS directs, collect(DISTINCT neighbor) AS neighbors,
                 collect(DISTINCT creator) AS creators
            UNWIND [p] + directs + neighbors + creators AS n
            WITH DISTINCT n
            WHERE n IS NOT NULL
            RETURN n, labels(n)[0] AS type
            """,
            project_id=str(project_id),
        )
        for record in node_records:
            n = record["n"]
            props = dict(n)
            ntype = record["type"]
            nid = props.get("id") or props.get("path") or f"{ntype}:{props.get('name', '')}"
            label = (
                props.get("name")
                or props.get("title")
                or props.get("full_name")
                or props.get("runtime_slug")
                or props.get("path")
                or nid
            )
            nodes.append(
                GraphNode(
                    id=str(nid),
                    type=ntype,
                    label=str(label),
                    properties={k: v for k, v in props.items() if k not in ("id", "project_id")},
                )
            )

        node_ids = [n.id for n in nodes]
        if node_ids:
            edge_records = session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE (a.id IN $node_ids OR a.path IN $node_ids)
                  AND (b.id IN $node_ids OR b.path IN $node_ids)
                RETURN DISTINCT coalesce(a.id, a.path) AS source, coalesce(b.id, b.path) AS target, type(r) AS rel_type
                """,
                node_ids=node_ids,
            )
            for record in edge_records:
                edges.append(
                    GraphEdge(source=record["source"], target=record["target"], type=record["rel_type"])
                )

    return GraphResult(connected=True, detail="OK", nodes=nodes, edges=edges)


def get_repository_graph(project_id, repo_id=None) -> GraphResult:
    """Returns the code-level graph of the repository: Repository, Directories,
    Files, Classes, Functions, Modules, and their relationships."""
    ok, detail = health_check()
    if not ok:
        return GraphResult(connected=False, detail=detail)

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    with _driver().session() as session:
        records = session.run(
            """
            MATCH (p:Project {id: $project_id})
            OPTIONAL MATCH (p)-[:HAS_REPOSITORY]->(r:Repository)
            OPTIONAL MATCH (r)-[:CONTAINS]->(d:Directory)
            OPTIONAL MATCH (p)-[:HAS_FILE]->(f:File)
            OPTIONAL MATCH (f)-[:DEFINES]->(s)
            OPTIONAL MATCH (f)-[:IMPORTS]->(m:Module)
            WITH r, collect(DISTINCT d) AS dirs, collect(DISTINCT f) AS files,
                 collect(DISTINCT s) AS symbols, collect(DISTINCT m) AS modules
            UNWIND ([r] + dirs + files + symbols + modules) AS n
            WITH DISTINCT n
            WHERE n IS NOT NULL
            RETURN n, labels(n)[0] AS type
            LIMIT 300
            """,
            project_id=str(project_id),
        )
        for record in records:
            n = record["n"]
            props = dict(n)
            ntype = record["type"]
            nid = props.get("id") or props.get("path") or f"{ntype}:{props.get('name', '')}"
            label = (
                props.get("full_name")
                or props.get("name")
                or props.get("path")
                or nid
            )
            nodes.append(
                GraphNode(
                    id=str(nid),
                    type=ntype,
                    label=str(label),
                    properties={k: v for k, v in props.items() if k not in ("id", "project_id")},
                )
            )

        node_id_map = {n.id: n for n in nodes}
        edge_records = session.run(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_REPOSITORY]->(r:Repository)
            OPTIONAL MATCH (r)-[:CONTAINS]->(d:Directory)
            OPTIONAL MATCH (r)-[:HAS_FILE]->(f:File)
            OPTIONAL MATCH (f)-[:DEFINES]->(s)
            OPTIONAL MATCH (f)-[:IMPORTS]->(m:Module)
            WITH [
                CASE WHEN r IS NOT NULL AND d IS NOT NULL THEN {source: coalesce(r.id, r.full_name), target: d.path, type: 'CONTAINS'} END,
                CASE WHEN r IS NOT NULL AND f IS NOT NULL THEN {source: coalesce(r.id, r.full_name), target: f.path, type: 'HAS_FILE'} END,
                CASE WHEN f IS NOT NULL AND s IS NOT NULL THEN {source: f.path, target: labels(s)[0] + ':' + s.name, type: 'DEFINES'} END,
                CASE WHEN f IS NOT NULL AND m IS NOT NULL THEN {source: f.path, target: 'Module:' + m.name, type: 'IMPORTS'} END
            ] AS rels
            UNWIND rels AS rel
            WITH DISTINCT rel
            WHERE rel IS NOT NULL
            RETURN rel.source AS source, rel.target AS target, rel.type AS type
            LIMIT 500
            """,
            project_id=str(project_id),
        )
        for record in edge_records:
            src = str(record["source"])
            tgt = str(record["target"])
            if src in node_id_map and tgt in node_id_map:
                edges.append(GraphEdge(source=src, target=tgt, type=record["type"]))

    return GraphResult(connected=True, detail="OK", nodes=nodes, edges=edges)
