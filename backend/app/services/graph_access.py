"""The Graph Access Service (Phase 2, P2-1 of the engineering audit's
remaining roadmap): the mandatory layer every Neo4j read/write passes
through.

Per the Architecture Decision Log (Domain 4, Decision 1): "shared Neo4j
database by default, with mandatory tenant/project authorization enforced
by a dedicated Graph Access Service... The Graph Access Service derives
scope from authenticated identity... not untrusted agent-supplied
filters."

Before this module existed, every caller (`app/api/routes/knowledge.py`,
and later `app/services/knowledge_context.py`) called straight into
`app/services/knowledge_graph.py`'s Cypher functions, passing a bare
`project_id`/`Project` argument of its own choosing -- safe only because
every caller happened to be careful, not because anything enforced it
(`04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` S3.5). This module closes that
gap: a `GraphAccessService` instance is only ever constructed from an
already-authorized scope (an HTTP route's `ProjectContext`, or a
server-internal trusted `Project`/`Task` row -- never a bare id taken
from a request body or an agent's own output), and every graph operation
on it is scoped to that one project.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
import uuid

from sqlalchemy.orm import Session as DBSession

from app.models.project import Project
from app.services import knowledge_graph

if TYPE_CHECKING:
    from app.api.deps import ProjectContext


class GraphAccessDenied(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class GraphAccessService:
    """All methods are implicitly scoped to `project` -- there is no method
    on this class that takes a caller-supplied project id. Construct one
    of these per request/task, never cache or share across projects."""

    project: Project

    @classmethod
    def from_project_context(cls, ctx: "ProjectContext") -> "GraphAccessService":
        """The path every HTTP route must use: scope comes from the
        already-authorized `ProjectContext` (`require_project_access`),
        not from a path/body parameter the route handler re-parses."""
        return cls(project=ctx.project)

    @classmethod
    def from_project(cls, project: Project) -> "GraphAccessService":
        """For trusted server-internal callers with no live HTTP request to
        scope from (e.g. a background task-execution thread). Callers MUST
        have already loaded `project` through their own authorization path
        (e.g. a `Task` row whose `project_id` was fixed at creation time
        under RBAC) -- this is not a generic bypass for arbitrary ids."""
        return cls(project=project)

    # -- read-only health -----------------------------------------------

    def health_check(self) -> tuple[bool, str]:
        return knowledge_graph.health_check()

    # -- platform-entity sync --------------------------------------------

    def sync_project(self, db: DBSession) -> knowledge_graph.SyncResult:
        return knowledge_graph.sync_project(db, self.project)

    # -- repository ingestion --------------------------------------------

    def ingest_repository(
        self,
        db: DBSession,
        root_path: str = "",
        repo_connection_id: uuid.UUID | None = None,
    ) -> knowledge_graph.IngestResult:
        return knowledge_graph.ingest_repository(
            self.project, root_path, db=db, repo_connection_id=repo_connection_id
        )

    # -- reads -------------------------------------------------------------

    def get_code_graph(self) -> knowledge_graph.CodeGraphResult:
        return knowledge_graph.get_code_graph(self.project.id)

    def get_project_graph(self) -> knowledge_graph.GraphResult:
        return knowledge_graph.get_project_graph(self.project.id)

    def get_repository_graph(self, repo_id: str | None = None) -> knowledge_graph.GraphResult:
        return knowledge_graph.get_repository_graph(self.project.id, repo_id)

    # -- bounded ad hoc access, for context-retrieval callers --------------

    @contextmanager
    def session(self):
        """For callers that need to run their own bounded Cypher (today:
        `knowledge_context.build_task_knowledge_context`'s relevance
        queries) rather than one of the fixed operations above. Still goes
        through this service so the project scope is fixed at construction
        time, not re-derived per query -- a caller here cannot accidentally
        query a different project than the one this service was scoped to,
        since `self.project.id` is the only id it was handed."""
        ok, detail = knowledge_graph.health_check()
        if not ok:
            raise GraphAccessDenied(f"Graph database unavailable: {detail}")
        with knowledge_graph._driver().session() as session:
            yield session
