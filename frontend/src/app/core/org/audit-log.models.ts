export interface ApiAuditLog {
  id: string;
  organization_id: string | null;
  actor_user_id: string | null;
  action: string;
  target_type: string;
  target_id: string;
  extra: Record<string, unknown>;
  created_at: string;
}
