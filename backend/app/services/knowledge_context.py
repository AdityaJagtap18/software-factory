"""Context construction service for coding-agent execution.

Automatically retrieves available project knowledge and repository code intelligence
from Neo4j / Postgres and constructs a bounded, agent-readable instruction block.
Gracefully degrades if Neo4j or repository context is unavailable.
"""

from dataclasses import dataclass, field
import re
import uuid

import neo4j
from sqlalchemy.orm import Session as DBSession

from app.models.git_integration import RepositoryConnection, RepositoryConnectionStatus
from app.models.project import Project
from app.models.task import Task
from app.services.graph_access import GraphAccessService

_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were",
    "will", "with", "this", "task", "code", "file", "fix", "add", "update", "new"
}

_MAX_RELEVANT_FILES = 8
_MAX_RELEVANT_SYMBOLS = 12
_MAX_RELEVANT_DEPENDENCIES = 8


@dataclass
class KnowledgeContextResult:
    available: bool
    formatted_context: str
    entities_retrieved: int = 0
    relevant_files: list[str] = field(default_factory=list)
    relevant_symbols: list[dict] = field(default_factory=list)
    relevant_dependencies: list[str] = field(default_factory=list)
    repository_name: str = ""
    indexed_at: str | None = None
    error: str = ""

    @property
    def metadata(self) -> dict:
        return {
            "available": self.available,
            "retrieved": not bool(self.error),
            "entities_retrieved": self.entities_retrieved,
            "total_entities": self.entities_retrieved,
            "files_count": len(self.relevant_files),
            "symbols_count": len(self.relevant_symbols),
            "relevant_files": self.relevant_files,
            "repository_name": self.repository_name,
            "indexed_at": self.indexed_at,
            "error": self.error,
        }


def _extract_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_]{3,}", text)
    keywords: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        lower = tok.lower()
        if lower not in _STOP_WORDS and lower not in seen:
            seen.add(lower)
            keywords.append(lower)
    return keywords[:10]


def build_task_knowledge_context(db: DBSession, task: Task) -> KnowledgeContextResult:
    """Retrieves relevant project and repository graph context for a task.

    Bounded by relevance heuristics (title and description tokens matching
    indexed file paths, class/function symbols, or dependencies). Never fabricates
    data. If Neo4j is offline or the repo is not indexed, gracefully reports
    available=False without failing task execution.
    """
    project = db.get(Project, task.project_id)
    if project is None:
        return KnowledgeContextResult(
            available=False,
            formatted_context="",
            error="Project not found.",
        )

    # Identify connected repository
    repo_conn = (
        db.query(RepositoryConnection)
        .filter(
            RepositoryConnection.project_id == task.project_id,
            RepositoryConnection.status == RepositoryConnectionStatus.CONNECTED,
        )
        .first()
    )
    repo_name = repo_conn.full_name if repo_conn else ""
    default_branch = (repo_conn.default_branch if repo_conn else "") or "main"

    graph_access = GraphAccessService.from_project(project)
    ok, detail = graph_access.health_check()
    if not ok:
        # Graceful degradation when graph DB is unavailable
        context_text = (
            "=== PROJECT KNOWLEDGE CONTEXT ===\n"
            f"Project: {project.name}\n"
            + (f"Connected repository: {repo_name} (branch: {default_branch})\n" if repo_name else "")
            + "Knowledge Graph: Unavailable (Neo4j connection offline)\n"
            "Instructions:\n"
            "- Inspect the checked-out repository source code as the source of truth.\n"
            "================================="
        )
        return KnowledgeContextResult(
            available=False,
            formatted_context=context_text,
            repository_name=repo_name,
            error=f"Graph database offline: {detail}",
        )

    # Extract search terms from task title & description
    search_text = f"{task.title} {task.description or ''}"
    keywords = _extract_keywords(search_text)

    relevant_files: list[str] = []
    relevant_symbols: list[dict] = []
    relevant_dependencies: list[str] = []
    indexed_at: str | None = None
    entities_count = 0

    try:
        with graph_access.session() as session:
            # Check repository node in graph
            repo_res = session.run(
                """
                MATCH (p:Project {id: $project_id})
                OPTIONAL MATCH (p)-[:HAS_REPOSITORY]->(r:Repository)
                RETURN r.synced_at AS synced_at, r.full_name AS full_name
                LIMIT 1
                """,
                project_id=str(project.id),
            ).single()

            if repo_res and repo_res["synced_at"]:
                indexed_at = repo_res["synced_at"]
                if not repo_name and repo_res["full_name"]:
                    repo_name = repo_res["full_name"]

            # Query relevant files matching search terms or general files if none match
            if keywords:
                file_records = session.run(
                    """
                    MATCH (p:Project {id: $project_id})-[:HAS_FILE]->(f:File)
                    WHERE any(term IN $terms WHERE toLower(f.path) CONTAINS term)
                    RETURN f.path AS path, f.language AS language
                    LIMIT $limit
                    """,
                    project_id=str(project.id),
                    terms=keywords,
                    limit=_MAX_RELEVANT_FILES,
                )
            else:
                file_records = session.run(
                    """
                    MATCH (p:Project {id: $project_id})-[:HAS_FILE]->(f:File)
                    RETURN f.path AS path, f.language AS language
                    LIMIT $limit
                    """,
                    project_id=str(project.id),
                    limit=_MAX_RELEVANT_FILES,
                )

            for rec in file_records:
                path = rec["path"]
                lang = rec["language"] or ""
                relevant_files.append(f"{path} ({lang})" if lang else path)
                entities_count += 1

            # Query relevant symbols (Classes, Functions)
            if keywords:
                symbol_records = session.run(
                    """
                    MATCH (p:Project {id: $project_id})-[:HAS_FILE]->(f:File)-[:DEFINES]->(s)
                    WHERE any(term IN $terms WHERE toLower(s.name) CONTAINS term or toLower(f.path) CONTAINS term)
                    RETURN f.path AS path, s.name AS name, s.line AS line, labels(s)[0] AS kind
                    LIMIT $limit
                    """,
                    project_id=str(project.id),
                    terms=keywords,
                    limit=_MAX_RELEVANT_SYMBOLS,
                )
                for rec in symbol_records:
                    relevant_symbols.append({
                        "name": rec["name"],
                        "kind": rec["kind"],
                        "path": rec["path"],
                        "line": rec["line"],
                    })
                    entities_count += 1

            # Query relevant modules/dependencies
            if keywords:
                dep_records = session.run(
                    """
                    MATCH (p:Project {id: $project_id})-[:HAS_FILE]->(f:File)-[:IMPORTS]->(m:Module)
                    WHERE any(term IN $terms WHERE toLower(m.name) CONTAINS term)
                    RETURN DISTINCT m.name AS name
                    LIMIT $limit
                    """,
                    project_id=str(project.id),
                    terms=keywords,
                    limit=_MAX_RELEVANT_DEPENDENCIES,
                )
                for rec in dep_records:
                    if rec["name"]:
                        relevant_dependencies.append(rec["name"])
                        entities_count += 1

            # If standard File/Symbol nodes were sparse, consult Graphify Entity nodes
            if len(relevant_files) < 3 or len(relevant_symbols) < 3:
                graphify_records = session.run(
                    """
                    MATCH (e:Entity {project_id: $project_id})
                    WHERE e.type IN ['File', 'Class', 'Function', 'API', 'Test']
                      AND ($has_keywords = false OR any(term IN $terms WHERE toLower(e.label) CONTAINS term OR toLower(e.file_path) CONTAINS term))
                    RETURN e.label AS label, e.type AS type, e.file_path AS file_path, e.location AS location
                    LIMIT 20
                    """,
                    project_id=str(project.id),
                    terms=keywords,
                    has_keywords=bool(keywords),
                )
                for grec in graphify_records:
                    etype = grec["type"]
                    elabel = grec["label"]
                    efile = grec["file_path"] or ""
                    eloc = grec["location"] or ""
                    if etype in ("File", "Test") and efile and efile not in relevant_files:
                        relevant_files.append(efile)
                        entities_count += 1
                    elif etype in ("Class", "Function", "API") and elabel not in [s["name"] for s in relevant_symbols]:
                        relevant_symbols.append({
                            "name": elabel,
                            "kind": etype,
                            "path": efile,
                            "line": eloc,
                        })
                        entities_count += 1

    except Exception as exc:  # noqa: BLE001
        # Neo4j query failure shouldn't abort execution
        return KnowledgeContextResult(
            available=False,
            formatted_context=(
                "=== PROJECT KNOWLEDGE CONTEXT ===\n"
                f"Project: {project.name}\n"
                f"Connected repository: {repo_name}\n"
                f"Knowledge retrieval note: {exc}\n"
                "Instructions:\n"
                "- Inspect the repository source files directly.\n"
                "================================="
            ),
            repository_name=repo_name,
            error=str(exc),
        )

    # Format context block
    context_lines = [
        "=== PROJECT KNOWLEDGE CONTEXT ===",
        f"Project: {project.name}",
    ]
    if repo_name:
        context_lines.append(f"Connected repository: {repo_name} (branch: {default_branch})")
    if indexed_at:
        context_lines.append(f"Repository graph indexed at: {indexed_at}")

    if relevant_files:
        context_lines.append("\nRelevant files:")
        for rf in relevant_files:
            context_lines.append(f"- {rf}")
    else:
        context_lines.append("\nRelevant files: (None identified in graph index for this task query)")

    if relevant_symbols:
        context_lines.append("\nRelevant symbols:")
        for s in relevant_symbols:
            context_lines.append(f"- {s['name']} ({s['kind']}) in {s['path']}:{s['line']}")

    if relevant_dependencies:
        context_lines.append("\nRelevant dependencies/modules:")
        for dep in relevant_dependencies:
            context_lines.append(f"- {dep}")

    context_lines.extend([
        "\nInstructions:",
        "- Use this information when it is relevant to the task.",
        "- Inspect the actual source files before making changes.",
        "- Treat repository source code as the source of truth.",
        "- Do not assume graph metadata is more current than the checked-out repository.",
        "- If graph context is unavailable, continue using the actual repository normally.",
        "- Never invent missing graph information.",
        "=================================",
    ])

    return KnowledgeContextResult(
        available=entities_count > 0 or bool(indexed_at),
        formatted_context="\n".join(context_lines),
        entities_retrieved=entities_count,
        relevant_files=relevant_files,
        relevant_symbols=relevant_symbols,
        relevant_dependencies=relevant_dependencies,
        repository_name=repo_name,
        indexed_at=indexed_at,
    )
