export interface DashboardActivityItem {
  id: string;
  action: string;
  target_type: string;
  target_id: string;
  actor_name: string | null;
  created_at: string;
}

export interface DashboardRunningWorkflow {
  id: string;
  name: string;
  project_name: string;
  current_step: number;
  total_steps: number;
  progress_percent: number;
  elapsed_seconds: number;
}

export interface DashboardHealthItem {
  name: string;
  connected: boolean;
  detail: string;
}

export interface DashboardSummary {
  organizations: number;
  projects: number;
  tasks_total: number;
  tasks_running: number;
  workflows_total: number;
  workflows_running: number;
  connections_configured: number;
  recent_activity: DashboardActivityItem[];
  running_workflows: DashboardRunningWorkflow[];
  system_health: DashboardHealthItem[];
}
