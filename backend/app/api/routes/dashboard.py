from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.dashboard import DashboardSummaryResponse
from app.services import dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Real counts and real recent activity across every organization and
    project this user actually belongs to -- the same access rule enforced
    by `require_project_access` elsewhere, not "everything in the DB."
    """
    summary = dashboard.get_summary(db, user)
    return DashboardSummaryResponse(
        organizations=summary.organizations,
        projects=summary.projects,
        tasks_total=summary.tasks_total,
        tasks_running=summary.tasks_running,
        workflows_total=summary.workflows_total,
        workflows_running=summary.workflows_running,
        connections_configured=summary.connections_configured,
        recent_activity=[
            {
                "id": a.id,
                "action": a.action,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "actor_name": a.actor_name,
                "created_at": a.created_at,
            }
            for a in summary.recent_activity
        ],
        running_workflows=[
            {
                "id": w.id,
                "name": w.name,
                "project_name": w.project_name,
                "current_step": w.current_step,
                "total_steps": w.total_steps,
                "progress_percent": w.progress_percent,
                "elapsed_seconds": w.elapsed_seconds,
            }
            for w in summary.running_workflows
        ],
        system_health=[
            {"name": h.name, "connected": h.connected, "detail": h.detail}
            for h in summary.system_health
        ],
    )
