import { ApiTask } from './task.models';

export type WorkflowStatus = 'not_started' | 'running' | 'completed' | 'failed';

export interface ApiWorkflow {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: WorkflowStatus;
  current_step_index: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  steps: ApiTask[];
}

export interface MyApiWorkflow extends ApiWorkflow {
  project_name: string;
}

export interface CreateWorkflowStepPayload {
  title: string;
  description?: string;
  coding_agent_connection_id?: string | null;
}

export interface CreateWorkflowPayload {
  name: string;
  description?: string;
  steps: CreateWorkflowStepPayload[];
}
