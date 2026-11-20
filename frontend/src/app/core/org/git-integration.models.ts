export type InstallationStatus = 'not_connected' | 'connected' | 'revoked';
export type RepositoryConnectionStatus = 'not_connected' | 'connected' | 'error';
export type WebhookConfigStatus = 'not_configured' | 'registered';

export interface GitInstallation {
  id: string;
  organization_id: string;
  provider: string;
  external_installation_id: string;
  account_login: string;
  status: InstallationStatus;
  last_error: string;
  last_health_check_at: string | null;
}

export interface CreateGitInstallationPayload {
  external_installation_id: string;
  account_login?: string;
}

export interface RepositorySummary {
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  private: boolean;
}

export interface RepositoryConnection {
  id: string;
  project_id: string;
  git_installation_id: string;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  selected_working_branches: string[];
  status: RepositoryConnectionStatus;
  permission_scope: string;
  last_error: string;
  last_successful_sync_at: string | null;
  last_observed_commit_sha: string;
  webhook_config_status: WebhookConfigStatus;
}

export interface CreateRepositoryConnectionPayload {
  git_installation_id: string;
  owner: string;
  name: string;
  selected_working_branches?: string[];
}

export interface BranchSummary {
  name: string;
  commit_sha: string;
  protected: boolean;
}

export interface CreateBranchPayload {
  name: string;
  from_branch?: string;
}

export interface BranchComparisonCommit {
  sha: string;
  message: string;
  author_login: string;
  authored_at: string | null;
}

export interface BranchComparison {
  ahead_by: number;
  behind_by: number;
  commits: BranchComparisonCommit[];
  diff_text: string;
}

export interface MergePullRequestResult {
  merged: boolean;
  sha: string;
  message: string;
}

export interface CreateRepositoryPayload {
  git_installation_id: string;
  name: string;
  private?: boolean;
  selected_working_branches?: string[];
}
