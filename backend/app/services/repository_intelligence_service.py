from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Optional
import uuid

import networkx as nx
from networkx.algorithms.community import louvain_communities
from sqlalchemy import desc
from sqlalchemy.orm import Session as DBSession

COMMUNITY_COLORS = [
    "#38bdf8",  # sky blue
    "#fb923c",  # orange
    "#f43f5e",  # rose / pink
    "#2dd4bf",  # teal
    "#a3e635",  # lime
    "#facc15",  # yellow
    "#c084fc",  # purple
    "#f472b6",  # light pink
    "#818cf8",  # indigo
    "#34d399",  # emerald
    "#fbbf24",  # amber
    "#e879f9",  # fuchsia
    "#60a5fa",  # blue
    "#4ade80",  # green
    "#f87171",  # red
    "#94a3b8",  # slate
]

_COMMUNITY_NOISE_LABELS = {
    "with", "and", "key", "tags", "item", "data", "text", "args", "kwargs",
    "none", "self", "true", "false", "str", "int", "bool", "dict", "list",
    "container", "contents", "image-ref", "pull_request", "alias", "context"
}


from app.core.config import get_settings
from app.models.git_integration import RepositoryConnection, RepositoryConnectionStatus
from app.models.project import Project
from app.models.repository_intelligence import (
    IndexingRunStatus,
    RepositoryIndexingRun,
    RepositoryIntelligenceSetting,
)
from app.schemas.repository_intelligence import (
    BranchInfo,
    CommitInfo,
    CommunityPayload,
    DependenciesResponse,
    DependencyCycle,
    ExternalDependencyItem,
    GraphEdgePayload,
    GraphNodePayload,
    GraphResponse,
    HistoryDiffResponse,
    HistoryResponse,
    HistoryRunItem,
    ImpactResponse,
    IndexRunDetailResponse,
    IndexStatusSummary,
    InternalDependencyItem,
    NodeDetailResponse,
    NodeNeighborsResponse,
    OverviewMetrics,
    OverviewResponse,
    RepoBranchListResponse,
    SearchResponse,
    SearchResultItem,
    SettingsResponse,
    SettingsUpdateRequest,
)
from app.services.graphify_adapter import (
    NormalizedEdge,
    NormalizedNode,
    run_graphify_extraction,
)
from app.services.knowledge_graph import _driver, _sync_connected_repo_checkout, health_check

logger = logging.getLogger(__name__)


def _scoped_id(project_id: str, repo_id: str, branch: str, raw_id: str) -> str:
    return f"{project_id}:{repo_id}:{branch}:{raw_id}"


def get_repository_branches(
    db: DBSession, project_id: uuid.UUID, repository_id: uuid.UUID
) -> RepoBranchListResponse:
    rc = db.get(RepositoryConnection, repository_id)
    if not rc or rc.project_id != project_id:
        raise ValueError(f"Repository {repository_id} not found in project {project_id}")

    default_branch = rc.default_branch or "main"
    branch_names = [default_branch]
    if rc.selected_working_branches:
        for b in rc.selected_working_branches:
            if b not in branch_names:
                branch_names.append(b)

    # If repository is cloned locally, check git branches
    cache_root = Path(get_settings().worktree_root_dir).resolve() / "repo_cache"
    repo_dir = cache_root / f"{rc.owner}_{rc.name}"
    if repo_dir.exists() and (repo_dir / ".git").exists():
        try:
            res = subprocess.run(
                ["git", "branch", "-r"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    cleaned = line.strip().replace("origin/", "").replace("HEAD ->", "").strip()
                    if cleaned and not cleaned.startswith("origin") and cleaned not in branch_names:
                        branch_names.append(cleaned)
        except Exception:
            pass

    branches = [
        BranchInfo(
            name=b,
            is_default=(b == default_branch),
            last_commit_sha=rc.last_observed_commit_sha or "",
        )
        for b in branch_names
    ]

    return RepoBranchListResponse(
        repository_id=str(rc.id),
        repository_name=rc.full_name,
        default_branch=default_branch,
        current_branch=default_branch,
        branches=branches,
    )


def get_or_create_settings(
    db: DBSession, project_id: uuid.UUID, repository_id: uuid.UUID
) -> RepositoryIntelligenceSetting:
    setting = (
        db.query(RepositoryIntelligenceSetting)
        .filter_by(project_id=project_id, repository_connection_id=repository_id)
        .first()
    )
    if not setting:
        rc = db.get(RepositoryConnection, repository_id)
        def_branch = (rc.default_branch if rc else "") or "main"
        setting = RepositoryIntelligenceSetting(
            project_id=project_id,
            repository_connection_id=repository_id,
            default_branch=def_branch,
            included_paths=[],
            excluded_paths=["node_modules", "dist", ".git", "__pycache__", "venv", ".venv", "build"],
            max_file_size_kb=500,
            auto_index_on_sync=True,
        )
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


def update_settings(
    db: DBSession, project_id: uuid.UUID, data: SettingsUpdateRequest
) -> SettingsResponse:
    repo_uuid = uuid.UUID(data.repository_connection_id)
    setting = get_or_create_settings(db, project_id, repo_uuid)

    if data.default_branch is not None:
        setting.default_branch = data.default_branch
    if data.included_paths is not None:
        setting.included_paths = data.included_paths
    if data.excluded_paths is not None:
        setting.excluded_paths = data.excluded_paths
    if data.max_file_size_kb is not None:
        setting.max_file_size_kb = data.max_file_size_kb
    if data.auto_index_on_sync is not None:
        setting.auto_index_on_sync = data.auto_index_on_sync

    db.commit()
    db.refresh(setting)

    return SettingsResponse(
        project_id=str(setting.project_id),
        repository_connection_id=str(setting.repository_connection_id),
        default_branch=setting.default_branch,
        included_paths=setting.included_paths,
        excluded_paths=setting.excluded_paths,
        max_file_size_kb=setting.max_file_size_kb,
        auto_index_on_sync=setting.auto_index_on_sync,
    )


def index_repository(
    db: DBSession,
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    branch: Optional[str] = None,
    force: bool = False,
) -> RepositoryIndexingRun:
    start_time = time.time()
    rc = db.get(RepositoryConnection, repository_id)
    if not rc or rc.project_id != project_id:
        raise ValueError(f"Repository {repository_id} not found in project {project_id}")

    target_branch = branch or rc.default_branch or "main"
    settings = get_or_create_settings(db, project_id, repository_id)

    run = RepositoryIndexingRun(
        project_id=project_id,
        repository_connection_id=repository_id,
        branch=target_branch,
        status=IndexingRunStatus.RUNNING.value,
        graphify_version="0.9.113",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    logs: list[str] = [f"[{datetime.now(timezone.utc).isoformat()}] Starting indexing for {rc.full_name} on branch {target_branch}"]

    try:
        # Step 1: Ensure repository checkout
        logs.append("Step 1/5: Synchronizing Git repository checkout...")
        repo_dir = _sync_connected_repo_checkout(rc)
        logs.append(f"Repository checkout ready at {repo_dir}")

        # Checkout target branch if different
        try:
            subprocess.run(["git", "checkout", target_branch], cwd=str(repo_dir), capture_output=True, text=True, timeout=30)
        except Exception as exc:
            logs.append(f"Branch checkout notice: {exc}")

        # Get latest commit SHA
        commit_sha = ""
        try:
            res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_dir), capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                commit_sha = res.stdout.strip()
                run.commit_sha = commit_sha
        except Exception:
            pass

        # Step 2: Code Extraction with Graphify
        logs.append("Step 2/5: Running Graphify code analysis & AST extraction...")
        extraction_result = run_graphify_extraction(
            repo_path=repo_dir,
            excluded_paths=settings.excluded_paths,
            max_file_size_kb=settings.max_file_size_kb,
        )
        logs.append(extraction_result.log_output)

        # Step 3: Graph Normalization & Validation
        logs.append(f"Step 3/5: Normalizing {len(extraction_result.nodes)} nodes and {len(extraction_result.edges)} edges...")

        # Step 4: Neo4j Persistence
        logs.append("Step 4/5: Persisting normalized graph into Neo4j...")
        neo4j_ok, detail = health_check()
        if not neo4j_ok:
            raise RuntimeError(f"Neo4j connection failed: {detail}")

        pid_str = str(project_id)
        rid_str = str(repository_id)

        with _driver().session() as session:
            # Clear previous graph for this project/repository/branch
            session.run(
                """
                MATCH (n:Entity {project_id: $project_id, repository_id: $repo_id, branch: $branch})
                DETACH DELETE n
                """,
                project_id=pid_str,
                repo_id=rid_str,
                branch=target_branch,
            )

            # Insert nodes in batches
            batch_size = 500
            for i in range(0, len(extraction_result.nodes), batch_size):
                batch = extraction_result.nodes[i : i + batch_size]
                node_params = [
                    {
                        "id": _scoped_id(pid_str, rid_str, target_branch, n.id),
                        "raw_id": n.id,
                        "label": n.label,
                        "type": n.type,
                        "file_path": n.file_path or "",
                        "location": n.location or "",
                        "project_id": pid_str,
                        "repository_id": rid_str,
                        "branch": target_branch,
                        "commit_sha": commit_sha,
                        "properties": json.dumps(n.properties),
                    }
                    for n in batch
                ]
                session.run(
                    """
                    UNWIND $batch AS item
                    MERGE (n:Entity {id: item.id})
                    SET n.raw_id = item.raw_id,
                        n.label = item.label,
                        n.type = item.type,
                        n.file_path = item.file_path,
                        n.location = item.location,
                        n.project_id = item.project_id,
                        n.repository_id = item.repository_id,
                        n.branch = item.branch,
                        n.commit_sha = item.commit_sha,
                        n.properties = item.properties
                    """,
                    batch=node_params,
                )

            # Insert edges in batches
            valid_node_ids = {n.id for n in extraction_result.nodes}
            valid_edges = [
                e for e in extraction_result.edges if e.source in valid_node_ids and e.target in valid_node_ids
            ]

            for i in range(0, len(valid_edges), batch_size):
                batch_edges = valid_edges[i : i + batch_size]
                edge_params = [
                    {
                        "source": _scoped_id(pid_str, rid_str, target_branch, e.source),
                        "target": _scoped_id(pid_str, rid_str, target_branch, e.target),
                        "type": e.type,
                        "provenance": e.provenance,
                        "weight": e.weight,
                        "properties": json.dumps(e.properties),
                    }
                    for e in batch_edges
                ]
                session.run(
                    """
                    UNWIND $batch AS item
                    MATCH (s:Entity {id: item.source})
                    MATCH (t:Entity {id: item.target})
                    MERGE (s)-[r:RELATION {type: item.type}]->(t)
                    SET r.provenance = item.provenance,
                        r.weight = item.weight,
                        r.properties = item.properties
                    """,
                    batch=edge_params,
                )

        logs.append(f"Step 5/5: Successfully persisted {len(extraction_result.nodes)} nodes and {len(valid_edges)} relationships.")
        
        # Complete run
        duration = round(time.time() - start_time, 2)
        run.status = IndexingRunStatus.COMPLETED.value
        run.entities_count = len(extraction_result.nodes)
        run.relationships_count = len(valid_edges)
        run.duration_seconds = duration
        run.log_output = "\n".join(logs)
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        return run

    except Exception as exc:
        duration = round(time.time() - start_time, 2)
        logs.append(f"ERROR: Indexing failed: {exc}")
        run.status = IndexingRunStatus.FAILED.value
        run.duration_seconds = duration
        run.error_message = str(exc)
        run.log_output = "\n".join(logs)
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        return run


def get_overview(
    db: DBSession,
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    branch: Optional[str] = None,
) -> OverviewResponse:
    rc = db.get(RepositoryConnection, repository_id)
    if not rc or rc.project_id != project_id:
        raise ValueError(f"Repository {repository_id} not found in project {project_id}")

    target_branch = branch or rc.default_branch or "main"

    latest_run = (
        db.query(RepositoryIndexingRun)
        .filter_by(project_id=project_id, repository_connection_id=repository_id, branch=target_branch)
        .order_by(desc(RepositoryIndexingRun.started_at))
        .first()
    )

    metrics = OverviewMetrics()
    recent_commits: list[CommitInfo] = []

    # Get recent commits from local checkout
    cache_root = Path(get_settings().worktree_root_dir).resolve() / "repo_cache"
    repo_dir = cache_root / f"{rc.owner}_{rc.name}"
    if repo_dir.exists() and (repo_dir / ".git").exists():
        try:
            res = subprocess.run(
                ["git", "log", "-n", "8", "--pretty=format:%H|%an|%ad|%s", "--date=short"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.splitlines():
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        recent_commits.append(
                            CommitInfo(sha=parts[0][:8], author=parts[1], date=parts[2], message=parts[3])
                        )
        except Exception:
            pass

    # Query Neo4j for actual entity counts if available
    neo4j_ok, _ = health_check()
    if neo4j_ok:
        try:
            with _driver().session() as session:
                counts_res = session.run(
                    """
                    MATCH (n:Entity {project_id: $pid, repository_id: $rid, branch: $branch})
                    RETURN n.type AS type, count(n) AS c
                    """,
                    pid=str(project_id),
                    rid=str(repository_id),
                    branch=target_branch,
                )
                for record in counts_res:
                    t = record["type"]
                    c = record["c"]
                    if t == "File":
                        metrics.total_files = c
                    elif t == "Directory":
                        metrics.total_directories = c
                    elif t == "Class":
                        metrics.total_classes = c
                    elif t in ("Function", "Method", "API"):
                        metrics.total_functions += c
                    elif t == "External":
                        metrics.external_dependencies_count = c

                # Count distinct languages
                file_res = session.run(
                    """
                    MATCH (n:Entity {project_id: $pid, repository_id: $rid, branch: $branch, type: 'File'})
                    RETURN n.file_path AS path
                    """,
                    pid=str(project_id),
                    rid=str(repository_id),
                    branch=target_branch,
                )
                from app.services.graphify_adapter import _LANGUAGE_EXTENSIONS
                langs: dict[str, int] = {}
                for rec in file_res:
                    p = rec["path"]
                    if p:
                        ext = Path(p).suffix.lower()
                        lang = _LANGUAGE_EXTENSIONS.get(ext, "Other")
                        langs[lang] = langs.get(lang, 0) + 1
                metrics.languages = langs
        except Exception as exc:
            logger.debug(f"Neo4j query error during overview: {exc}")

    index_status = IndexStatusSummary(
        last_indexed_at=latest_run.completed_at if latest_run else None,
        status=latest_run.status if latest_run else "NOT_INDEXED",
        commit_sha=latest_run.commit_sha if latest_run else (rc.last_observed_commit_sha or ""),
        duration_seconds=latest_run.duration_seconds if latest_run else 0.0,
        graphify_version=latest_run.graphify_version if latest_run else "0.9.113",
        entities_count=latest_run.entities_count if latest_run else 0,
        relationships_count=latest_run.relationships_count if latest_run else 0,
    )

    return OverviewResponse(
        project_id=str(project_id),
        repository_id=str(repository_id),
        repository_name=rc.full_name,
        branch=target_branch,
        metrics=metrics,
        index_status=index_status,
        recent_commits=recent_commits,
    )


def _format_community_name(members: list[str], node_map: dict[str, GraphNodePayload], G_sub: nx.Graph, index: int) -> str:
    # Sort members by local subgraph degree descending
    sorted_members = sorted(members, key=lambda nid: G_sub.degree(nid) if nid in G_sub else 0, reverse=True)
    for nid in sorted_members:
        n = node_map.get(nid)
        if not n:
            continue
        lbl = n.label.strip()
        # Clean label (e.g. "routers/auth.py" -> "auth")
        clean_lbl = lbl.replace(".py", "").replace(".ts", "").replace(".js", "").replace("()", "").strip()
        if "/" in clean_lbl or "\\" in clean_lbl:
            clean_lbl = os.path.basename(clean_lbl)
        if clean_lbl.lower() not in _COMMUNITY_NOISE_LABELS and len(clean_lbl) >= 3 and not clean_lbl.startswith("."):
            return clean_lbl
    return f"Community {index + 1}"


def get_graph(
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    branch: Optional[str] = None,
    node_type: Optional[str] = None,
    limit: int = 400,
) -> GraphResponse:
    neo4j_ok, _ = health_check()
    if not neo4j_ok:
        return GraphResponse(
            project_id=str(project_id),
            repository_id=str(repository_id),
            branch=branch or "main",
            nodes=[],
            edges=[],
            communities=[],
        )

    b = branch or "main"
    nodes: list[GraphNodePayload] = []
    edges: list[GraphEdgePayload] = []
    communities: list[CommunityPayload] = []

    with _driver().session() as session:
        query = """
            MATCH (n:Entity {project_id: $pid, repository_id: $rid, branch: $branch})
            WHERE n.type IN ['File', 'Class', 'Function', 'Method', 'API', 'Test', 'Directory', 'External', 'Module']
        """
        params = {"pid": str(project_id), "rid": str(repository_id), "branch": b, "limit": limit}
        if node_type and node_type != "All":
            query += " AND n.type = $node_type"
            params["node_type"] = node_type
        query += " RETURN n LIMIT $limit"

        res = session.run(query, **params)
        node_id_map: dict[str, str] = {}
        nodes_dict: dict[str, GraphNodePayload] = {}

        for record in res:
            n = record["n"]
            raw_props = json.loads(n.get("properties", "{}")) if n.get("properties") else {}
            node_payload = GraphNodePayload(
                id=n["raw_id"] or n["id"],
                label=n["label"] or "",
                type=n["type"] or "File",
                file_path=n.get("file_path"),
                location=n.get("location"),
                properties=raw_props,
            )
            nodes.append(node_payload)
            node_id_map[n["id"]] = node_payload.id
            nodes_dict[node_payload.id] = node_payload

        if node_id_map:
            edge_res = session.run(
                """
                MATCH (s:Entity)-[r:RELATION]->(t:Entity)
                WHERE s.id IN $node_ids AND t.id IN $node_ids
                RETURN s.id AS s_id, t.id AS t_id, r.type AS rel_type, r.provenance AS prov, r.weight AS w, r.properties AS props
                LIMIT 1500
                """,
                node_ids=list(node_id_map.keys()),
            )
            seen_edges = set()
            for er in edge_res:
                s_nid = node_id_map[er["s_id"]]
                t_nid = node_id_map[er["t_id"]]
                edge_key = (s_nid, t_nid, er["rel_type"])
                if edge_key not in seen_edges and s_nid != t_nid:
                    seen_edges.add(edge_key)
                    props = json.loads(er.get("props", "{}")) if er.get("props") else {}
                    edges.append(
                        GraphEdgePayload(
                            source=s_nid,
                            target=t_nid,
                            type=er["rel_type"] or "REFERENCES",
                            provenance=er.get("prov") or "EXTRACTED",
                            weight=float(er.get("w") or 1.0),
                            properties=props,
                        )
                    )

    # Community Detection & Degree Calculation using NetworkX
    if nodes:
        G = nx.Graph()
        for n in nodes:
            G.add_node(n.id)
        for e in edges:
            if e.source in nodes_dict and e.target in nodes_dict:
                G.add_edge(e.source, e.target)

        # Set degree on each node
        for n in nodes:
            n.degree = G.degree(n.id) if n.id in G else 0

        # Louvain Community Detection
        try:
            raw_comms = list(louvain_communities(G, seed=42))
        except Exception as exc:
            logger.debug(f"Louvain community detection fallback: {exc}")
            raw_comms = [set(G.nodes())]

        # Sort communities by size descending
        sorted_comms = sorted(raw_comms, key=len, reverse=True)

        for i, comm_set in enumerate(sorted_comms):
            comm_id = f"comm_{i}"
            comm_color = COMMUNITY_COLORS[i % len(COMMUNITY_COLORS)]
            comm_members = list(comm_set)
            subgraph = G.subgraph(comm_set)
            comm_name = _format_community_name(comm_members, nodes_dict, subgraph, i)

            for member_id in comm_members:
                if member_id in nodes_dict:
                    nodes_dict[member_id].community_id = comm_id
                    nodes_dict[member_id].community_name = comm_name
                    nodes_dict[member_id].community_color = comm_color

            communities.append(
                CommunityPayload(
                    id=comm_id,
                    name=comm_name,
                    color=comm_color,
                    node_count=len(comm_members),
                    member_node_ids=comm_members,
                )
            )

    return GraphResponse(
        project_id=str(project_id),
        repository_id=str(repository_id),
        branch=b,
        nodes=nodes,
        edges=edges,
        communities=communities,
        total_nodes=len(nodes),
        total_edges=len(edges),
        truncated=(len(nodes) >= limit),
    )


def get_node_details(
    db: DBSession,
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    node_id: str,
    branch: Optional[str] = None,
) -> NodeDetailResponse:
    neo4j_ok, _ = health_check()
    b = branch or "main"
    scoped_id = _scoped_id(str(project_id), str(repository_id), b, node_id)

    target_node = GraphNodePayload(id=node_id, label=node_id, type="Unknown")
    incoming: list[GraphEdgePayload] = []
    outgoing: list[GraphEdgePayload] = []
    source_preview: Optional[str] = None

    if neo4j_ok:
        with _driver().session() as session:
            # Query the node
            res = session.run(
                """
                MATCH (n:Entity {id: $scoped_id})
                RETURN n
                """,
                scoped_id=scoped_id,
            ).single()
            if res:
                n = res["n"]
                raw_props = json.loads(n.get("properties", "{}")) if n.get("properties") else {}
                target_node = GraphNodePayload(
                    id=n.get("raw_id", node_id),
                    label=n.get("label", node_id),
                    type=n.get("type", "Unknown"),
                    file_path=n.get("file_path"),
                    location=n.get("location"),
                    properties=raw_props,
                )

            # Query outgoing
            out_res = session.run(
                """
                MATCH (s:Entity {id: $scoped_id})-[r:RELATION]->(t:Entity)
                RETURN t.raw_id AS t_id, r.type AS rel_type, r.provenance AS prov, r.weight AS w
                LIMIT 50
                """,
                scoped_id=scoped_id,
            )
            for r in out_res:
                outgoing.append(
                    GraphEdgePayload(
                        source=node_id,
                        target=r["t_id"],
                        type=r["rel_type"] or "REFERENCES",
                        provenance=r.get("prov") or "EXTRACTED",
                        weight=float(r.get("w") or 1.0),
                    )
                )

            # Query incoming
            in_res = session.run(
                """
                MATCH (s:Entity)-[r:RELATION]->(t:Entity {id: $scoped_id})
                RETURN s.raw_id AS s_id, r.type AS rel_type, r.provenance AS prov, r.weight AS w
                LIMIT 50
                """,
                scoped_id=scoped_id,
            )
            for r in in_res:
                incoming.append(
                    GraphEdgePayload(
                        source=r["s_id"],
                        target=node_id,
                        type=r["rel_type"] or "REFERENCES",
                        provenance=r.get("prov") or "EXTRACTED",
                        weight=float(r.get("w") or 1.0),
                    )
                )

    # Read source snippet if available
    rc = db.get(RepositoryConnection, repository_id)
    if rc and target_node.file_path:
        cache_root = Path(get_settings().worktree_root_dir).resolve() / "repo_cache"
        repo_dir = cache_root / f"{rc.owner}_{rc.name}"
        fpath = repo_dir / target_node.file_path
        if fpath.exists() and fpath.is_file():
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                # If location like L15, slice around it
                start_line = 0
                if target_node.location and target_node.location.startswith("L"):
                    try:
                        line_num = int(target_node.location[1:])
                        start_line = max(0, line_num - 5)
                        end_line = min(len(lines), line_num + 20)
                        source_preview = "\n".join(lines[start_line:end_line])
                    except ValueError:
                        source_preview = "\n".join(lines[:40])
                else:
                    source_preview = "\n".join(lines[:40])
            except Exception:
                pass

    return NodeDetailResponse(
        node=target_node,
        incoming=incoming,
        outgoing=outgoing,
        source_preview=source_preview,
    )


def get_node_neighbors(
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    node_id: str,
    branch: Optional[str] = None,
    depth: int = 1,
) -> NodeNeighborsResponse:
    neo4j_ok, _ = health_check()
    b = branch or "main"
    scoped_id = _scoped_id(str(project_id), str(repository_id), b, node_id)

    nodes: list[GraphNodePayload] = []
    edges: list[GraphEdgePayload] = []

    if neo4j_ok:
        with _driver().session() as session:
            res = session.run(
                """
                MATCH (center:Entity {id: $scoped_id})
                OPTIONAL MATCH (center)-[r:RELATION]-(neighbor:Entity)
                RETURN center, neighbor, r, startNode(r).raw_id AS s_raw, endNode(r).raw_id AS t_raw
                LIMIT 50
                """,
                scoped_id=scoped_id,
            )
            seen_ids = set()
            for rec in res:
                c = rec["center"]
                if c and c["raw_id"] not in seen_ids:
                    seen_ids.add(c["raw_id"])
                    nodes.append(
                        GraphNodePayload(
                            id=c["raw_id"],
                            label=c.get("label", c["raw_id"]),
                            type=c.get("type", "Unknown"),
                            file_path=c.get("file_path"),
                            location=c.get("location"),
                        )
                    )
                n = rec["neighbor"]
                if n and n["raw_id"] not in seen_ids:
                    seen_ids.add(n["raw_id"])
                    nodes.append(
                        GraphNodePayload(
                            id=n["raw_id"],
                            label=n.get("label", n["raw_id"]),
                            type=n.get("type", "Unknown"),
                            file_path=n.get("file_path"),
                            location=n.get("location"),
                        )
                    )
                r = rec["r"]
                if r:
                    edges.append(
                        GraphEdgePayload(
                            source=rec["s_raw"],
                            target=rec["t_raw"],
                            type=r.get("type", "REFERENCES"),
                            provenance=r.get("provenance", "EXTRACTED"),
                            weight=float(r.get("weight", 1.0)),
                        )
                    )

    return NodeNeighborsResponse(center_node_id=node_id, nodes=nodes, edges=edges)


def search_code(
    db: DBSession,
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    branch: Optional[str] = None,
    query: str = "",
    mode: str = "all",
) -> SearchResponse:
    if not query.strip():
        return SearchResponse(query=query, mode=mode, total=0, results=[])

    q = query.strip().lower()
    b = branch or "main"
    results: list[SearchResultItem] = []
    seen = set()

    # 1. Search Neo4j graph for files and symbols
    neo4j_ok, _ = health_check()
    if neo4j_ok and mode in ("all", "file", "symbol", "intent"):
        with _driver().session() as session:
            cypher = """
                MATCH (n:Entity {project_id: $pid, repository_id: $rid, branch: $branch})
                WHERE toLower(n.label) CONTAINS $q OR toLower(n.file_path) CONTAINS $q
                RETURN n LIMIT 30
            """
            res = session.run(cypher, pid=str(project_id), rid=str(repository_id), branch=b, q=q)
            for rec in res:
                n = rec["n"]
                nid = n.get("raw_id", n["id"])
                fpath = n.get("file_path") or ""
                ntype = n.get("type", "Symbol")
                key = (nid, fpath)
                if key not in seen:
                    seen.add(key)
                    mtype = "file" if ntype == "File" else "symbol"
                    results.append(
                        SearchResultItem(
                            node_id=nid,
                            title=n.get("label", nid),
                            file_path=fpath,
                            line_number=int(n["location"][1:]) if n.get("location", "").startswith("L") and n["location"][1:].isdigit() else None,
                            match_type=mtype,
                            snippet=f"{ntype}: {n.get('label', '')} in {fpath}",
                            kind=ntype,
                        )
                    )

    # 2. Search local checkout files for content text
    rc = db.get(RepositoryConnection, repository_id)
    if rc and mode in ("all", "code", "intent"):
        cache_root = Path(get_settings().worktree_root_dir).resolve() / "repo_cache"
        repo_dir = cache_root / f"{rc.owner}_{rc.name}"
        if repo_dir.exists():
            for root, dirs, files in os.walk(repo_dir):
                dirs[:] = [d for d in dirs if d not in ["node_modules", ".git", "dist", "build", "__pycache__"]]
                for f in files:
                    if len(results) >= 40:
                        break
                    fpath = Path(root) / f
                    rel_path = os.path.relpath(fpath, repo_dir).replace("\\", "/")
                    try:
                        content = fpath.read_text(encoding="utf-8", errors="ignore")
                        for idx, line in enumerate(content.splitlines(), start=1):
                            if q in line.lower():
                                key = (rel_path, idx)
                                if key not in seen:
                                    seen.add(key)
                                    results.append(
                                        SearchResultItem(
                                            node_id=f"file:{rel_path}",
                                            title=f,
                                            file_path=rel_path,
                                            line_number=idx,
                                            match_type="code",
                                            snippet=line.strip()[:160],
                                            kind="Code Match",
                                        )
                                    )
                                    if len(results) >= 40:
                                        break
                    except Exception:
                        pass

    return SearchResponse(query=query, mode=mode, total=len(results), results=results)


def get_dependencies(
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    branch: Optional[str] = None,
) -> DependenciesResponse:
    neo4j_ok, _ = health_check()
    b = branch or "main"
    internal: list[InternalDependencyItem] = []
    external: list[ExternalDependencyItem] = []
    cycles: list[DependencyCycle] = []

    if not neo4j_ok:
        return DependenciesResponse()

    # Build NetworkX DiGraph for cycle detection
    G = nx.DiGraph()

    with _driver().session() as session:
        # Internal dependencies
        res = session.run(
            """
            MATCH (s:Entity {project_id: $pid, repository_id: $rid, branch: $branch})-[r:RELATION]->(t:Entity {project_id: $pid, repository_id: $rid, branch: $branch})
            WHERE r.type IN ['IMPORTS', 'CALLS', 'DEPENDS_ON'] AND t.type <> 'External'
            RETURN s.raw_id AS s_id, s.file_path AS s_file, t.raw_id AS t_id, r.type AS rel_type, r.provenance AS prov
            LIMIT 500
            """,
            pid=str(project_id),
            rid=str(repository_id),
            branch=b,
        )
        for r in res:
            s_id = r["s_id"] or ""
            t_id = r["t_id"] or ""
            internal.append(
                InternalDependencyItem(
                    source_node=s_id,
                    source_file=r["s_file"] or "",
                    target_node=t_id,
                    relation=r["rel_type"] or "DEPENDS_ON",
                    provenance=r.get("prov") or "EXTRACTED",
                )
            )
            G.add_edge(s_id, t_id)

        # External dependencies
        ext_res = session.run(
            """
            MATCH (s:Entity {project_id: $pid, repository_id: $rid, branch: $branch})-[r:RELATION]->(t:Entity {project_id: $pid, repository_id: $rid, branch: $branch, type: 'External'})
            RETURN t.label AS name, t.properties AS props, collect(DISTINCT s.file_path) AS deps
            """,
            pid=str(project_id),
            rid=str(repository_id),
            branch=b,
        )
        for er in ext_res:
            props = json.loads(er.get("props", "{}")) if er.get("props") else {}
            dep_files = [f for f in er.get("deps", []) if f]
            external.append(
                ExternalDependencyItem(
                    name=er["name"] or "package",
                    version=props.get("version", ""),
                    manifest_file=props.get("manifest", ""),
                    usage_count=len(dep_files),
                    dependent_files=dep_files,
                )
            )

    # Detect cycles using NetworkX
    try:
        found_cycles = list(nx.simple_cycles(G))
        for c in found_cycles[:10]:
            cycles.append(DependencyCycle(nodes=c, length=len(c)))
    except Exception as exc:
        logger.debug(f"Cycle detection error: {exc}")

    return DependenciesResponse(
        internal=internal,
        external=external,
        cycles=cycles,
        total_internal=len(internal),
        total_external=len(external),
        cycles_count=len(cycles),
    )


def get_impact_analysis(
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
    node_id: str,
    branch: Optional[str] = None,
) -> ImpactResponse:
    neo4j_ok, _ = health_check()
    b = branch or "main"
    scoped_id = _scoped_id(str(project_id), str(repository_id), b, node_id)

    target_node = GraphNodePayload(id=node_id, label=node_id, type="Target")
    direct_consumers: list[GraphNodePayload] = []
    transitive_consumers: list[GraphNodePayload] = []
    affected_tests: list[GraphNodePayload] = []
    affected_apis: list[GraphNodePayload] = []
    has_inferred = False

    if neo4j_ok:
        with _driver().session() as session:
            # 1. Target node
            t_res = session.run("MATCH (n:Entity {id: $scoped_id}) RETURN n", scoped_id=scoped_id).single()
            if t_res:
                n = t_res["n"]
                target_node = GraphNodePayload(
                    id=n.get("raw_id", node_id),
                    label=n.get("label", node_id),
                    type=n.get("type", "Target"),
                    file_path=n.get("file_path"),
                    location=n.get("location"),
                )

            # 2. Direct consumers (1 hop)
            d_res = session.run(
                """
                MATCH (consumer:Entity)-[r:RELATION]->(target:Entity {id: $scoped_id})
                WHERE r.type IN ['CALLS', 'IMPORTS', 'USES', 'DEPENDS_ON', 'REFERENCES', 'TESTS']
                RETURN DISTINCT consumer, r.provenance AS prov
                LIMIT 50
                """,
                scoped_id=scoped_id,
            )
            direct_ids = set()
            for rec in d_res:
                c = rec["consumer"]
                cid = c.get("raw_id", c["id"])
                if cid != node_id and cid not in direct_ids:
                    direct_ids.add(cid)
                    payload = GraphNodePayload(
                        id=cid,
                        label=c.get("label", cid),
                        type=c.get("type", "Unknown"),
                        file_path=c.get("file_path"),
                        location=c.get("location"),
                    )
                    direct_consumers.append(payload)
                    if c.get("type") == "Test" or "test" in c.get("label", "").lower():
                        affected_tests.append(payload)
                    if c.get("type") == "API" or "api" in c.get("label", "").lower() or "controller" in c.get("label", "").lower():
                        affected_apis.append(payload)
                    if rec.get("prov") == "INFERRED":
                        has_inferred = True

            # 3. Transitive consumers (2 to 4 hops)
            trans_res = session.run(
                """
                MATCH path = (consumer:Entity)-[:RELATION*2..4]->(target:Entity {id: $scoped_id})
                RETURN DISTINCT consumer
                LIMIT 50
                """,
                scoped_id=scoped_id,
            )
            for rec in trans_res:
                c = rec["consumer"]
                cid = c.get("raw_id", c["id"])
                if cid != node_id and cid not in direct_ids:
                    payload = GraphNodePayload(
                        id=cid,
                        label=c.get("label", cid),
                        type=c.get("type", "Unknown"),
                        file_path=c.get("file_path"),
                        location=c.get("location"),
                    )
                    transitive_consumers.append(payload)
                    if c.get("type") == "Test" or "test" in c.get("label", "").lower():
                        affected_tests.append(payload)
                    if c.get("type") == "API" or "api" in c.get("label", "").lower() or "controller" in c.get("label", "").lower():
                        affected_apis.append(payload)

    confidence = 0.85 if has_inferred else 1.0
    summary = (
        f"Modifying '{target_node.label}' will directly impact {len(direct_consumers)} consumers "
        f"and transitively impact {len(transitive_consumers)} upstream components, "
        f"including {len(affected_tests)} test suites and {len(affected_apis)} API endpoints."
    )

    return ImpactResponse(
        target_node=target_node,
        direct_consumers=direct_consumers,
        transitive_consumers=transitive_consumers,
        affected_tests=affected_tests,
        affected_apis=affected_apis,
        confidence=confidence,
        summary=summary,
    )


def get_history(
    db: DBSession,
    project_id: uuid.UUID,
    repository_id: uuid.UUID,
) -> HistoryResponse:
    runs = (
        db.query(RepositoryIndexingRun)
        .filter_by(project_id=project_id, repository_connection_id=repository_id)
        .order_by(desc(RepositoryIndexingRun.started_at))
        .all()
    )

    items = [
        HistoryRunItem(
            id=str(r.id),
            branch=r.branch,
            commit_sha=r.commit_sha or "",
            status=r.status,
            graphify_version=r.graphify_version,
            entities_count=r.entities_count,
            relationships_count=r.relationships_count,
            duration_seconds=r.duration_seconds,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )
        for r in runs
    ]

    return HistoryResponse(runs=items)


def diff_history(
    db: DBSession,
    run_a_id: uuid.UUID,
    run_b_id: uuid.UUID,
) -> HistoryDiffResponse:
    run_a = db.get(RepositoryIndexingRun, run_a_id)
    run_b = db.get(RepositoryIndexingRun, run_b_id)
    if not run_a or not run_b:
        raise ValueError("Indexing runs not found for comparison")

    entities_diff = run_b.entities_count - run_a.entities_count
    relationships_diff = run_b.relationships_count - run_a.relationships_count

    return HistoryDiffResponse(
        run_a_id=str(run_a.id),
        run_b_id=str(run_b.id),
        entities_added=max(0, entities_diff),
        entities_removed=max(0, -entities_diff),
        relationships_added=max(0, relationships_diff),
        relationships_removed=max(0, -relationships_diff),
        details={
            "run_a_commit": run_a.commit_sha,
            "run_b_commit": run_b.commit_sha,
            "run_a_branch": run_a.branch,
            "run_b_branch": run_b.branch,
        },
    )
