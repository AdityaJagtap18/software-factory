export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  my_role: 'org_admin' | 'member';
}

export type ProjectRole = 'project_admin' | 'developer' | 'reviewer' | 'viewer';

export interface ApiProject {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string;
  repository_url: string;
  status: 'Active' | 'In Progress' | 'Paused' | 'Archived';
  my_role: ProjectRole;
}
