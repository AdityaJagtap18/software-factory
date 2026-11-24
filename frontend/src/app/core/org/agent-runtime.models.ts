export interface Capability {
  name: string;
  state: 'declared' | 'tested' | 'verified';
}

export interface RuntimeCatalogEntry {
  slug: string;
  name: string;
  description: string;
  icon: string;
  supported_connection_modes: string[];
  auth_method: string;
  capabilities: Capability[];
}

export type ConnectionMode = 'local_runtime' | 'factory_managed' | 'custom_adapter';
export type ConnectionStatus = 'not_configured' | 'not_connected' | 'connected' | 'error';

export interface AgentConnection {
  id: string | null;
  is_configured: boolean;
  organization_id: string;
  runtime_slug: string;
  runtime_name: string;
  icon: string;
  description: string;
  connection_mode: ConnectionMode | null;
  auth_method: string;
  status: ConnectionStatus;
  detected_version: string;
  last_error: string;
  last_health_check_at: string | null;
  has_credential: boolean;
  capabilities: Capability[];
}

export interface CreateConnectionPayload {
  runtime_slug: string;
  connection_mode: ConnectionMode;
  credential_name?: string;
  credential_provider?: string;
  credential_value?: string;
}

export interface ModelOption {
  id: string; // composite key e.g. "claude_code:claude-3-7-sonnet"
  provider_id: string;
  provider_name: string;
  model_id: string;
  model_name: string;
  runtime_slug: string;
  runtime_name: string;
  display_name: string;
  connection_id: string | null;
  connection_status: string;
  availability_status: 'CONNECTED' | 'AVAILABLE' | 'DISCONNECTED' | 'UNAVAILABLE' | 'MISCONFIGURED' | 'ERROR';
  capabilities: Capability[];
  execution_supported: boolean;
  selection_allowed: boolean;
  version?: string;
  description?: string;
  is_default?: boolean;
}

export interface ProviderGroup {
  provider_id: string;
  provider_name: string;
  icon: string;
  models: ModelOption[];
}

export interface ModelCatalogResponse {
  groups: ProviderGroup[];
  models: ModelOption[];
  default_model_id: string | null;
  selected_model_id: string | null;
}
