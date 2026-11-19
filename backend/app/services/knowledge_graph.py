"""Syncs a project's real tasks, workflows, and coding-agent connections
into Neo4j as a genuine graph of what actually happened in the factory —
never a fabricated entity/relationship count. If Neo4j is unreachable,
every call here honestly reports `connected: False` with the real driver
error; it never returns a fake empty-but-successful graph.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import neo4j
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models.agent_runtime import CodingAgentConnection
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow import Workflow
from app.services import code_ingestion


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


def sync_project(db: DBSession, project: Project) -> SyncResult:
    ok, detail = health_check()
    if not ok:
        return SyncResult(connected=False, detail=detail)

    tasks = db.query(Task).filter_by(project_id=project.id).all()
    workflows = db.query(Workflow).filter_by(project_id=project.id).all()
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


def ingest_repository(project: Project, root_path: str) -> IngestResult:
    """Parses a real directory of source files on the backend host and
    upserts real File/Function/Class nodes into Neo4j, replacing whatever
    this project's previous code-structure nodes were -- so a file or
    symbol that genuinely no longer exists on disk doesn't linger as a
    stale node after re-ingestion. This never fetches a remote git URL;
    `root_path` must be a directory the backend process can already see,
    which keeps this from becoming an arbitrary-fetch/SSRF vector."""
    ok, detail = health_check()
    if not ok:
        return IngestResult(connected=False, detail=detail)

    try:
        files = code_ingestion.scan_directory(Path(root_path))
    except code_ingestion.IngestionError as exc:
        return IngestResult(connected=False, detail=exc.message)

    synced_at = datetime.now(timezone.utc)
    nodes_synced = 0
    relationships_synced = 0
    symbols_found = sum(len(f.symbols) for f in files)

    with _driver().session() as session:
        # Drop this project's previous code-structure subgraph before
        # re-creating it from the current, real state of disk.
        session.run(
            """
            MATCH (p:Project {id: $project_id})-[:HAS_FILE]->(f:File)
            OPTIONAL MATCH (f)-[:DEFINES]->(s)
            DETACH DELETE f, s
            """,
            project_id=str(project.id),
        )

        session.run(
            "MERGE (p:Project {id: $id}) SET p.name = $name",
            id=str(project.id),
            name=project.name,
        )

        for code_file in files:
            session.run(
                """
                MATCH (p:Project {id: $project_id})
                MERGE (f:File {project_id: $project_id, path: $path})
                SET f.language = $language
                MERGE (p)-[:HAS_FILE]->(f)
                """,
                project_id=str(project.id),
                path=code_file.relative_path,
                language=code_file.language,
            )
            nodes_synced += 1
            relationships_synced += 1

            for symbol in code_file.symbols:
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
    """Reads back the real File/Function/Class subgraph a prior
    `ingest_repository` call wrote for this project -- empty (not fake)
    if nothing has been ingested yet."""
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
        # The project itself, every task/workflow directly under it, and
        # every node one hop further out (connections, creators) -- the
        # real, bounded neighborhood of this project's synced data.
        node_records = session.run(
            """
            MATCH (p:Project {id: $project_id})
            OPTIONAL MATCH (p)-[:HAS_TASK|HAS_WORKFLOW]->(direct)
            OPTIONAL MATCH (direct)-[:ASSIGNED_TO|HAS_STEP]-(neighbor)
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
            nodes.append(
                GraphNode(
                    id=props["id"],
                    type=record["type"],
                    label=props.get("name") or props.get("title") or props.get("full_name")
                    or props.get("runtime_slug") or props["id"],
                    properties={k: v for k, v in props.items() if k != "id"},
                )
            )

        node_ids = [n.id for n in nodes]
        if node_ids:
            edge_records = session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE a.id IN $node_ids AND b.id IN $node_ids
                RETURN DISTINCT a.id AS source, b.id AS target, type(r) AS rel_type
                """,
                node_ids=node_ids,
            )
            for record in edge_records:
                edges.append(
                    GraphEdge(source=record["source"], target=record["target"], type=record["rel_type"])
                )

    return GraphResult(connected=True, detail="OK", nodes=nodes, edges=edges)
