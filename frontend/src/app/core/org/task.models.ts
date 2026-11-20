export type TaskPriority = 'low' | 'medium' | 'high';
export type TaskStatus = 'not_started' | 'running' | 'completed' | 'failed';

export interface ApiTask {
  id: string;
  project_id: string;
  title: string;
  description: string;
  priority: TaskPriority;
  status: TaskStatus;
  coding_agent_connection_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  output: string;
  error_message: string;
  created_at: string;
  git_branch_name: string;
  git_base_branch: string;
  git_changed_files: string[];
  git_pr_url: string;
  git_pr_number: number;
  git_pr_state: string;
  git_ci_status: string;
  git_base_branch_protected: boolean;
  git_required_status_checks: string[];
  git_required_approving_reviews: number;
}

export interface MyApiTask extends ApiTask {
  project_name: string;
}

export interface CreateTaskPayload {
  title: string;
  description?: string;
  priority?: TaskPriority;
  coding_agent_connection_id?: string | null;
}

export interface TaskDiff {
  git_branch_name: string;
  git_base_branch: string;
  git_changed_files: string[];
  git_diff: string;
}

export type TaskMessageRole = 'user' | 'agent' | 'system';

export interface TaskMessage {
  id: string;
  task_id: string;
  role: TaskMessageRole;
  content: string;
  created_at: string;
}
