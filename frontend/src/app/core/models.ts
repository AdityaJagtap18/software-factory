// Domain models for the Software Factory UI shell.
// These mirror the entities described in the architecture spec's data model
// (organizations, projects, tasks, executions, agents, prompts, approvals...)
// at the level of detail the UI needs. Mock data implements these interfaces
// so a real API client can be swapped in later without touching components.

export type StatusTone = 'green' | 'blue' | 'amber' | 'red' | 'gray' | 'violet';

export interface StatBadge {
  label: string;
  value: string | number;
  delta?: string;
  deltaDirection?: 'up' | 'down';
  icon: string;
  tone: 'blue' | 'violet' | 'green' | 'amber';
}

export interface Organization {
  id: string;
  name: string;
}

export interface Project {
  id: string;
  slug: string;
  name: string;
  description: string;
  repository: string;
  status: 'Active' | 'In Progress' | 'Paused' | 'Archived';
  activeWorkflows: number;
  lastActivity: string;
  icon: string;
  iconTone: 'blue' | 'violet' | 'green' | 'amber';
  branch: string;
  technologies: string[];
  lastSync: string;
  totalTasks: number;
  totalTasksDelta: string;
  workflowCount: number;
  workflowDelta: string;
  successRate: string;
  successRateDelta: string;
  avgExecutionTime: string;
  avgExecutionDelta: string;
}

export interface ActivityItem {
  id: string;
  icon: string;
  tone: StatusTone;
  title: string;
  subtitle: string;
  timestamp: string;
}

export interface RunningWorkflow {
  id: string;
  icon: string;
  name: string;
  project: string;
  currentStep: string;
  progress: number;
  eta: string;
}

export interface SystemHealthItem {
  icon: string;
  label: string;
  status: 'Healthy' | 'Degraded' | 'Down';
}

export interface TaskItem {
  id: string;
  title: string;
  description: string;
  status: 'In Progress' | 'Completed' | 'Pending Review' | 'Not Started' | 'Blocked';
  progress?: number;
  icon: string;
  project: string;
  priority: 'Low' | 'Medium' | 'High';
  branch: string;
  repository: string;
  type: string;
  createdBy: string;
  createdAt: string;
}

export interface ExecutionStep {
  label: string;
  status: 'completed' | 'active' | 'pending';
  detail?: string;
}

export interface ConversationMessage {
  id: string;
  author: string;
  authorKind: 'user' | 'supervisor' | 'agent';
  timestamp: string;
  body: string;
}

export interface AgentAssignment {
  name: string;
  icon: string;
  status: 'Completed' | 'Running' | 'Queued';
}

export interface WorkflowDagNode {
  id: string;
  label: string;
  icon: string;
  status: 'completed' | 'active' | 'pending';
  duration?: string;
  progress?: number;
  x: number;
  y: number;
}

export interface WorkflowDagEdge {
  from: string;
  to: string;
}

export interface Workflow {
  id: string;
  name: string;
  project: string;
  description: string;
  status: 'Running' | 'Completed' | 'Failed' | 'Queued';
  progress: number;
  startedAt: string;
  duration: string;
  orchestrator: string;
  nodes: WorkflowDagNode[];
  edges: WorkflowDagEdge[];
}

export interface AgentDefinition {
  id: string;
  name: string;
  description: string;
  icon: string;
  type: 'Development' | 'Quality' | 'Documentation' | 'Analysis' | 'Delivery';
  typeTone: StatusTone;
  model: string;
  status: 'Active' | 'Idle' | 'Offline';
  activeRuns: number;
  lastRun: string;
  capabilities: string[];
}

export interface CodeChange {
  path: string;
  name: string;
  added: number;
  removed: number;
  icon: string;
  language: string;
}

export interface ApprovalRequest {
  id: string;
  title: string;
  subtitle: string;
  priority: 'High' | 'Medium' | 'Low';
  category: string;
  project: string;
  timestamp: string;
  icon: string;
}

export interface PromptVersion {
  id: string;
  agent: string;
  name: string;
  description: string;
  body: string;
  version: string;
  status: 'Published' | 'In Review' | 'Draft';
  icon: string;
  updatedAt: string;
  owner: string;
  evalScore: number;
}

export interface ProviderConnection {
  id: string;
  name: string;
  type: 'Cloud' | 'Local';
  status: 'Healthy' | 'Degraded' | 'Down';
  models: number;
  lastChecked: string;
  icon: string;
}

export interface ModelCatalogEntry {
  id: string;
  model: string;
  provider: string;
  type: string;
  context: string;
  capabilities: string[];
  status: 'Active' | 'Inactive';
}

export interface MonitoringAlert {
  id: string;
  severity: 'High' | 'Medium' | 'Info';
  title: string;
  detail: string;
  timestamp: string;
}

export interface GraphEntity {
  id: string;
  label: string;
  type: string;
  icon: string;
  tone: StatusTone;
  x: number;
  y: number;
}

export interface GraphRelationship {
  from: string;
  to: string;
  label: string;
}

export interface RepoTreeNode {
  name: string;
  type: 'folder' | 'file';
  children?: RepoTreeNode[];
  active?: boolean;
}

export interface CodingAgentRuntime {
  id: string;
  name: string;
  description: string;
  icon: string;
  connectionMode: 'Local runtime' | 'Factory-managed' | 'Custom adapter';
  authMethod: string;
  status: 'Connected' | 'Not connected' | 'Not configured';
  version?: string;
  lastHealthCheck?: string;
  capabilities: string[];
}
