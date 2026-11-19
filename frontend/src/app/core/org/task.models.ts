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
