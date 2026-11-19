from datetime import datetime

from pydantic import BaseModel


class DashboardActivityItem(BaseModel):
    id: str
    action: str
    target_type: str
    target_id: str
    actor_name: str | None
    created_at: datetime


class DashboardRunningWorkflow(BaseModel):
    id: str
    name: str
    project_name: str
    current_step: int
    total_steps: int
    progress_percent: int
    elapsed_seconds: float


class DashboardHealthItem(BaseModel):
    name: str
    connected: bool
    detail: str


class DashboardSummaryResponse(BaseModel):
    organizations: int
    projects: int
    tasks_total: int
    tasks_running: int
    workflows_total: int
    workflows_running: int
    connections_configured: int
    recent_activity: list[DashboardActivityItem] = []
    running_workflows: list[DashboardRunningWorkflow] = []
    system_health: list[DashboardHealthItem] = []
