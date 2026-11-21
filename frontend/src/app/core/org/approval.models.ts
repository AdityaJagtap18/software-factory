export type ApprovalCategory =
  | 'code_change'
  | 'workflow_run'
  | 'knowledge_update'
  | 'prompt_change'
  | 'model_action'
  | 'access_security';

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'changes_requested';

export type ApprovalPriority = 'high' | 'medium' | 'low';

export interface ApiApproval {
  id: string;
  project_id: string;
  category: ApprovalCategory;
  status: ApprovalStatus;
  priority: ApprovalPriority;
  title: string;
  subtitle: string;
  task_id: string | null;
  requested_by_user_id: string | null;
  decided_by_user_id: string | null;
  decided_at: string | null;
  decision_note: string;
  created_at: string;
}

export interface ApprovalDecisionPayload {
  decision: 'approved' | 'rejected' | 'changes_requested';
  note?: string;
}
