"""Aggregates real counts and real recent activity for the current user
across every organization/project they actually belong to -- no
fabricated stat cards, no invented "ETA" on a running workflow, and no
blanket "All Services Operational" banner. Every number here is a real
COUNT()/query result, and system_health reports each dependency's real,
just-executed status.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.models.agent_runtime import CodingAgentConnection, ConnectionStatus
from app.models.audit import AuditLog
from app.models.organization import OrganizationMember
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.models.workflow import Workflow, WorkflowStatus
from app.services import knowledge_graph
from app.services.access import visible_project_ids


@dataclass
class ActivityItem:
    id: str
    action: str
    target_type: str
    target_id: str
    actor_name: str | None
    created_at: datetime


@dataclass
class RunningWorkflowSummary:
    id: str
    name: str
    project_name: str
    current_step: int
    total_steps: int
    progress_percent: int
    elapsed_seconds: float


@dataclass
class HealthItem:
    name: str
    connected: bool
    detail: str


@dataclass
class DashboardSummary:
    organizations: int = 0
    projects: int = 0
    tasks_total: int = 0
    tasks_running: int = 0
    workflows_total: int = 0
    workflows_running: int = 0
    connections_configured: int = 0
    recent_activity: list[ActivityItem] = field(default_factory=list)
    running_workflows: list[RunningWorkflowSummary] = field(default_factory=list)
    system_health: list[HealthItem] = field(default_factory=list)


def _postgres_health(db: DBSession) -> HealthItem:
    try:
        db.execute(text("SELECT 1"))
        return HealthItem(name="Postgres", connected=True, detail="Reachable")
    except Exception as exc:  # noqa: BLE001 - surface the real error, never fake one
        return HealthItem(name="Postgres", connected=False, detail=str(exc))


def _neo4j_health() -> HealthItem:
    ok, detail = knowledge_graph.health_check()
    return HealthItem(name="Neo4j (knowledge graph)", connected=ok, detail=detail)


def get_summary(db: DBSession, user: User) -> DashboardSummary:
    org_memberships = db.query(OrganizationMember).filter_by(user_id=user.id).all()
    org_ids = [m.organization_id for m in org_memberships]

    project_ids = visible_project_ids(db, user)

    tasks = db.query(Task).filter(Task.project_id.in_(project_ids)).all() if project_ids else []
    workflows = (
        db.query(Workflow).filter(Workflow.project_id.in_(project_ids)).all() if project_ids else []
    )
    connections = (
        db.query(CodingAgentConnection)
        .filter(CodingAgentConnection.organization_id.in_(org_ids))
        .all()
        if org_ids
        else []
    )

    running_workflows = [w for w in workflows if w.status == WorkflowStatus.RUNNING]
    projects_by_id = {p.id: p for p in db.query(Project).filter(Project.id.in_(project_ids)).all()} if project_ids else {}

    now = datetime.now(timezone.utc)
    running_summaries = []
    for w in running_workflows:
        total_steps = db.query(Task).filter_by(workflow_id=w.id).count()
        progress = int(round(100 * w.current_step_index / total_steps)) if total_steps else 0
        elapsed = (now - w.started_at).total_seconds() if w.started_at else 0.0
        running_summaries.append(
            RunningWorkflowSummary(
                id=str(w.id),
                name=w.name,
                project_name=projects_by_id.get(w.project_id).name if w.project_id in projects_by_id else "",
                current_step=w.current_step_index,
                total_steps=total_steps,
                progress_percent=progress,
                elapsed_seconds=elapsed,
            )
        )

    audit_entries = (
        db.query(AuditLog)
        .filter(AuditLog.organization_id.in_(org_ids))
        .order_by(AuditLog.created_at.desc())
        .limit(10)
        .all()
        if org_ids
        else []
    )
    actor_ids = {e.actor_user_id for e in audit_entries if e.actor_user_id}
    actors = {u.id: u.full_name for u in db.query(User).filter(User.id.in_(actor_ids)).all()} if actor_ids else {}

    recent_activity = [
        ActivityItem(
            id=str(e.id),
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            actor_name=actors.get(e.actor_user_id),
            created_at=e.created_at,
        )
        for e in audit_entries
    ]

    return DashboardSummary(
        organizations=len(org_ids),
        projects=len(project_ids),
        tasks_total=len(tasks),
        tasks_running=sum(1 for t in tasks if t.status == TaskStatus.RUNNING),
        workflows_total=len(workflows),
        workflows_running=len(running_workflows),
        connections_configured=sum(
            1 for c in connections if c.status != ConnectionStatus.NOT_CONFIGURED
        ),
        recent_activity=recent_activity,
        running_workflows=running_summaries,
        system_health=[_postgres_health(db), _neo4j_health()],
    )
