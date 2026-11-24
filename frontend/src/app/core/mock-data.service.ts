import { Injectable, signal } from '@angular/core';
import {
  ActivityItem,
  AgentAssignment,
  AgentDefinition,
  ApprovalRequest,
  CodeChange,
  CodingAgentRuntime,
  ConversationMessage,
  ExecutionStep,
  GraphEntity,
  GraphRelationship,
  ModelCatalogEntry,
  MonitoringAlert,
  Organization,
  PromptVersion,
  Project,
  ProviderConnection,
  RepoTreeNode,
  RunningWorkflow,
  StatBadge,
  SystemHealthItem,
  TaskItem,
  Workflow
} from './models';

/**
 * Mock data backing the UI shell. Every field here corresponds to a real
 * entity defined in the architecture's data model (docs/architecture). This
 * service is the single seam to swap for real HTTP calls against the FastAPI
 * control plane once it exists — components depend on these typed signals,
 * not on HTTP directly.
 */
@Injectable({ providedIn: 'root' })
export class MockDataService {
  readonly currentUser = signal({ name: 'Aditya Jagtap', initials: 'AJ' });

  readonly organizations = signal<Organization[]>([
    { id: 'org-coep', name: 'COEP Labs' },
    { id: 'org-acme', name: 'ACME Corp' }
  ]);

  readonly activeOrganization = signal<Organization>(this.organizations()[0]);

  readonly dashboardStats = signal<StatBadge[]>([
    { label: 'Active Projects', value: 6, delta: '+2', deltaDirection: 'up', icon: 'workspace/code-diff', tone: 'blue' },
    { label: 'Running Workflows', value: 4, delta: '+1', deltaDirection: 'up', icon: 'navigation/workflows', tone: 'violet' },
    { label: 'Tasks Completed', value: 128, delta: '+18%', deltaDirection: 'up', icon: 'status/success', tone: 'green' },
    { label: 'Artifacts Generated', value: 342, delta: '+21%', deltaDirection: 'up', icon: 'navigation/artifacts', tone: 'amber' }
  ]);

  readonly projects = signal<Project[]>([
    {
      id: 'fintrix', slug: 'FINTRIX', name: 'FINTRIX', description: 'Invoice Automation Platform',
      repository: 'fintrix-platform', status: 'Active', activeWorkflows: 2, lastActivity: '12 min ago',
      icon: 'navigation/workflows', iconTone: 'violet', branch: 'main',
      technologies: ['Java', 'Spring Boot', 'Angular', 'PostgreSQL'], lastSync: '18 Nov 2026, 04:17 PM',
      totalTasks: 214, totalTasksDelta: '+12%', workflowCount: 8, workflowDelta: '+2',
      successRate: '96.4%', successRateDelta: '+1.8%', avgExecutionTime: '14.2 min', avgExecutionDelta: '-22%'
    },
    {
      id: 'beacon', slug: 'BEACON', name: 'BEACON', description: 'Supply Chain Intelligence',
      repository: 'beacon-scm', status: 'Active', activeWorkflows: 1, lastActivity: '28 min ago',
      icon: 'navigation/artifacts', iconTone: 'blue', branch: 'main',
      technologies: ['Python', 'FastAPI', 'React'], lastSync: '18 Nov 2026, 03:40 PM',
      totalTasks: 96, totalTasksDelta: '+6%', workflowCount: 4, workflowDelta: '+1',
      successRate: '94.1%', successRateDelta: '+0.9%', avgExecutionTime: '11.6 min', avgExecutionDelta: '-8%'
    },
    {
      id: 'voyager-ai', slug: 'Voyager AI', name: 'Voyager AI', description: 'AI Travel Planning Platform',
      repository: 'voyager-ai', status: 'In Progress', activeWorkflows: 1, lastActivity: '1 hr ago',
      icon: 'agents/planning-agent', iconTone: 'amber', branch: 'develop',
      technologies: ['TypeScript', 'Node.js', 'Angular'], lastSync: '18 Nov 2026, 02:50 PM',
      totalTasks: 58, totalTasksDelta: '+22%', workflowCount: 3, workflowDelta: '0',
      successRate: '91.0%', successRateDelta: '+2.4%', avgExecutionTime: '18.9 min', avgExecutionDelta: '-4%'
    },
    {
      id: 'evalops', slug: 'EvalOps', name: 'EvalOps', description: 'LLM Evaluation & Observability',
      repository: 'evalops', status: 'In Progress', activeWorkflows: 0, lastActivity: '3 hrs ago',
      icon: 'navigation/settings', iconTone: 'violet', branch: 'main',
      technologies: ['Python', 'Langfuse'], lastSync: '18 Nov 2026, 01:05 PM',
      totalTasks: 31, totalTasksDelta: '+3%', workflowCount: 2, workflowDelta: '0',
      successRate: '88.7%', successRateDelta: '-1.1%', avgExecutionTime: '9.8 min', avgExecutionDelta: '+2%'
    }
  ]);

  readonly recentActivity = signal<ActivityItem[]>([
    { id: 'a1', icon: 'status/success', tone: 'green', title: 'Code review completed', subtitle: 'FINTRIX • PR #214 merged', timestamp: '12 min ago' },
    { id: 'a2', icon: 'navigation/workflows', tone: 'blue', title: 'Workflow started', subtitle: 'BEACON • Exception prioritization', timestamp: '28 min ago' },
    { id: 'a3', icon: 'navigation/artifacts', tone: 'amber', title: 'Artifact generated', subtitle: 'Voyager AI • Architecture document', timestamp: '1 hr ago' },
    { id: 'a4', icon: 'navigation/knowledge', tone: 'violet', title: 'Knowledge updated', subtitle: 'EvalOps • Design decision record (ADR)', timestamp: '3 hrs ago' }
  ]);

  readonly runningWorkflows = signal<RunningWorkflow[]>([
    { id: 'wkf-7842', icon: 'agents/planning-agent', name: 'Feature Implementation', project: 'FINTRIX', currentStep: 'Code Generation', progress: 72, eta: '~ 8 min' },
    { id: 'wkf-7840', icon: 'navigation/settings', name: 'Test Generation', project: 'BEACON', currentStep: 'Unit Test Creation', progress: 46, eta: '~ 14 min' },
    { id: 'wkf-7835', icon: 'agents/documentation-agent', name: 'Documentation Update', project: 'Voyager AI', currentStep: 'Drafting', progress: 31, eta: '~ 20 min' }
  ]);

  readonly systemHealth = signal<SystemHealthItem[]>([
    { icon: 'navigation/workflows', label: 'Orchestration (Temporal)', status: 'Healthy' },
    { icon: 'navigation/providers', label: 'AI Providers', status: 'Healthy' },
    { icon: 'navigation/repositories', label: 'Databases (PostgreSQL, Neo4j)', status: 'Healthy' },
    { icon: 'navigation/agents', label: 'Workers (Docker)', status: 'Healthy' }
  ]);

  readonly tasks = signal<TaskItem[]>([
    {
      id: 'TSK-4827', title: 'Implement Invoice OCR Extraction',
      description: 'Add OCR-based invoice extraction, validation, tests and documentation',
      status: 'In Progress', progress: 64, icon: 'navigation/workflows', project: 'FINTRIX', priority: 'High',
      branch: 'feature/invoice-ocr', repository: 'fintrix-platform', type: 'Feature',
      createdBy: 'Aditya Jagtap', createdAt: '18 Nov 2026, 10:24 AM'
    },
    {
      id: 'TSK-4819', title: 'Add invoice validation rules', description: 'Server-side validation for invoice line items',
      status: 'Completed', icon: 'status/success', project: 'FINTRIX', priority: 'Medium',
      branch: 'feature/invoice-validation', repository: 'fintrix-platform', type: 'Feature',
      createdBy: 'Aditya Jagtap', createdAt: '17 Nov 2026, 02:10 PM'
    },
    {
      id: 'TSK-4795', title: 'Create unit and integration tests', description: 'Coverage for the OCR extraction service',
      status: 'Completed', icon: 'agents/testing-agent', project: 'FINTRIX', priority: 'Medium',
      branch: 'feature/invoice-ocr', repository: 'fintrix-platform', type: 'Testing',
      createdBy: 'Factory (Orchestrator)', createdAt: '17 Nov 2026, 11:46 AM'
    },
    {
      id: 'TSK-4762', title: 'Update API documentation', description: 'Document invoice endpoints and OCR response schema',
      status: 'Pending Review', icon: 'agents/documentation-agent', project: 'FINTRIX', priority: 'Low',
      branch: 'feature/invoice-ocr', repository: 'fintrix-platform', type: 'Documentation',
      createdBy: 'Factory (Orchestrator)', createdAt: '16 Nov 2026, 05:02 PM'
    },
    {
      id: 'TSK-4728', title: 'Raise pull request and merge', description: 'Prepare PR for invoice validation rules',
      status: 'Not Started', icon: 'workspace/pull-request', project: 'FINTRIX', priority: 'Medium',
      branch: 'feature/invoice-validation', repository: 'fintrix-platform', type: 'Delivery',
      createdBy: 'Aditya Jagtap', createdAt: '16 Nov 2026, 09:30 AM'
    }
  ]);

  readonly taskExecutionSteps = signal<ExecutionStep[]>([
    { label: 'Requirements', status: 'completed' },
    { label: 'Plan', status: 'completed' },
    { label: 'Implement', status: 'active', detail: '64%' },
    { label: 'Test', status: 'pending' },
    { label: 'Review', status: 'pending' },
    { label: 'Complete', status: 'pending' }
  ]);

  readonly conversation = signal<ConversationMessage[]>([
    {
      id: 'm1', author: 'You', authorKind: 'user', timestamp: '10:24 AM',
      body: 'Implement invoice OCR extraction using Python. Add validation, write unit tests, update the API documentation and create a pull request.'
    },
    {
      id: 'm2', author: 'Factory (Orchestrator)', authorKind: 'supervisor', timestamp: '10:24 AM',
      body: "I've analyzed the requirement and prepared an execution plan. The coding agent has started implementation."
    },
    {
      id: 'm3', author: 'Coding Agent', authorKind: 'agent', timestamp: '10:37 AM',
      body: 'Implemented the OCR extraction service and core validation. Created the following files: invoice_ocr_service.py, validator.py, test_invoice_ocr.py, +2 more'
    }
  ]);

  readonly taskExecutionPlan = signal([
    { step: 'Analyze requirement & project context', status: 'Completed' as const },
    { step: 'Design approach & task breakdown', status: 'Completed' as const },
    { step: 'Implement OCR extraction service', status: 'In Progress (64%)' as const },
    { step: 'Add validation & error handling', status: 'Pending' as const },
    { step: 'Write unit and integration tests', status: 'Pending' as const },
    { step: 'Update API documentation', status: 'Pending' as const },
    { step: 'Create pull request', status: 'Pending' as const }
  ]);

  readonly taskAgentBreakdown = signal<AgentAssignment[]>([
    { name: 'Planning Agent', icon: 'agents/planning-agent', status: 'Completed' },
    { name: 'Coding Agent', icon: 'agents/coding-agent', status: 'Running' },
    { name: 'Testing Agent', icon: 'agents/testing-agent', status: 'Queued' },
    { name: 'Documentation Agent', icon: 'agents/documentation-agent', status: 'Queued' },
    { name: 'Review Agent', icon: 'agents/review-agent', status: 'Queued' }
  ]);

  readonly workflows = signal<Workflow[]>([
    {
      id: 'WKF-7842', name: 'Feature Implementation', project: 'FINTRIX',
      description: 'Implement invoice extraction module with tests and documentation',
      status: 'Running', progress: 72, startedAt: '18 Nov 2026, 04:21 PM', duration: '4m 32s (in progress)',
      orchestrator: 'Temporal',
      nodes: [
        { id: 'start', label: 'Start', icon: '', status: 'completed', x: 0, y: 1 },
        { id: 'analyze', label: 'Analyze Requirements', icon: 'workspace/code-search', status: 'completed', duration: '1m 24s', x: 1, y: 1 },
        { id: 'design', label: 'Design Solution', icon: 'navigation/workflows', status: 'completed', duration: '2m 10s', x: 2, y: 0 },
        { id: 'generate', label: 'Generate Code', icon: 'agents/coding-agent', status: 'active', progress: 72, x: 2, y: 1 },
        { id: 'tests', label: 'Generate Tests', icon: 'agents/testing-agent', status: 'completed', duration: '1m 58s', x: 2, y: 2 },
        { id: 'review', label: 'Review & Fix', icon: 'agents/review-agent', status: 'pending', x: 3, y: 1 },
        { id: 'docs', label: 'Update Documentation', icon: 'agents/documentation-agent', status: 'pending', x: 4, y: 1 },
        { id: 'end', label: 'End', icon: '', status: 'pending', x: 5, y: 1 }
      ],
      edges: [
        { from: 'start', to: 'analyze' }, { from: 'analyze', to: 'design' }, { from: 'analyze', to: 'generate' },
        { from: 'analyze', to: 'tests' }, { from: 'design', to: 'review' }, { from: 'generate', to: 'review' },
        { from: 'tests', to: 'review' }, { from: 'review', to: 'docs' }, { from: 'docs', to: 'end' }
      ]
    }
  ]);

  readonly agents = signal<AgentDefinition[]>([
    { id: 'AGT-CODE-001', name: 'Code Generation Agent', description: 'Generates, modifies and refactors code based on tasks', icon: 'agents/coding-agent', type: 'Development', typeTone: 'blue', model: 'Qwen3 14B', status: 'Active', activeRuns: 3, lastRun: '2 min ago',
      capabilities: ['Code Generation', 'Refactoring', 'Bug Fixing', 'Code Explanation', 'Diff Generation', 'Multi-language'] },
    { id: 'AGT-TEST-001', name: 'Test Generation Agent', description: 'Creates unit, integration and test data', icon: 'agents/testing-agent', type: 'Quality', typeTone: 'green', model: 'Llama 3.1 8B', status: 'Active', activeRuns: 1, lastRun: '6 min ago',
      capabilities: ['Unit Tests', 'Integration Tests', 'Test Data', 'Coverage Analysis'] },
    { id: 'AGT-DOC-001', name: 'Documentation Agent', description: 'Generates and updates technical docs', icon: 'agents/documentation-agent', type: 'Documentation', typeTone: 'blue', model: 'Gemini 2.5', status: 'Active', activeRuns: 1, lastRun: '9 min ago',
      capabilities: ['API Docs', 'README Updates', 'Changelogs'] },
    { id: 'AGT-PLAN-001', name: 'Requirement Analysis Agent', description: 'Analyzes PRDs and creates task plans', icon: 'agents/planning-agent', type: 'Analysis', typeTone: 'amber', model: 'GPT-4o', status: 'Idle', activeRuns: 0, lastRun: '42 min ago',
      capabilities: ['Requirement Analysis', 'Task Decomposition', 'DAG Planning'] },
    { id: 'AGT-REV-001', name: 'Review & Secure Code Agent', description: 'Code review, quality and security checks', icon: 'agents/review-agent', type: 'Quality', typeTone: 'green', model: 'Llama Guard', status: 'Active', activeRuns: 2, lastRun: '5 min ago',
      capabilities: ['Code Review', 'Security Scan', 'Best Practices'] },
    { id: 'AGT-DEP-001', name: 'Deployment Agent', description: 'Builds, packages and creates deployment artifacts', icon: 'agents/supervisor-agent', type: 'Delivery', typeTone: 'violet', model: 'GPT-4o mini', status: 'Idle', activeRuns: 0, lastRun: '1 hr ago',
      capabilities: ['Build', 'Package', 'Deployment Artifacts'] }
  ]);

  readonly codeChanges = signal<CodeChange[]>([
    { path: 'src/service/invoice_ocr_service.py', name: 'invoice_ocr_service.py', added: 312, removed: 27, icon: 'workspace/code-diff', language: 'python' },
    { path: 'src/service/validator.py', name: 'validator.py', added: 86, removed: 12, icon: 'workspace/code-diff', language: 'python' },
    { path: 'tests/test_invoice_ocr.py', name: 'test_invoice_ocr.py', added: 72, removed: 18, icon: 'agents/testing-agent', language: 'python' },
    { path: 'docs/api_docs.md', name: 'api_docs.md', added: 12, removed: 7, icon: 'agents/documentation-agent', language: 'markdown' }
  ]);

  readonly approvals = signal<ApprovalRequest[]>([
    { id: 'APR-1', title: 'Pull Request Creation', subtitle: 'TSK-4827: Implement Invoice OCR Extraction', priority: 'High', category: 'Code Change', project: 'FINTRIX', timestamp: '10 min ago', icon: 'workspace/pull-request' },
    { id: 'APR-2', title: 'Promote Knowledge to Project', subtitle: 'Add OCR design doc to project knowledge base', priority: 'Medium', category: 'Knowledge', project: 'FINTRIX', timestamp: '24 min ago', icon: 'navigation/knowledge' },
    { id: 'APR-3', title: 'Publish Updated Agent Prompt', subtitle: 'Update Coding Agent system prompt v2.3', priority: 'Medium', category: 'Agent / Prompt', project: 'Platform', timestamp: '37 min ago', icon: 'agents/coding-agent' }
  ]);

  readonly prompts = signal<PromptVersion[]>([
    {
      id: 'PR-1', agent: 'Coding Agent', name: 'Coding Agent – Implementation', description: 'Generates, modifies and refactors code with...', version: 'v2.3', status: 'Published', icon: 'agents/coding-agent', updatedAt: '16 Nov 2026, 11:24 AM', owner: 'Aditya Jagtap', evalScore: 0.91,
      body: `You are a Senior Software Engineer in the Software Factory.
Your task is to implement, modify, or refactor code based on the given requirement.

### Context
- Project: {{project_name}}
- Repository: {{repository}}

### Instructions
1. Understand the requirement and relevant context from the repository.
2. Identify impacted files using the repository knowledge graph.
3. Implement the changes following project coding standards.
4. Write or update unit and integration tests.
5. Update documentation (if applicable).`
    },
    {
      id: 'PR-2', agent: 'Planning Agent', name: 'Planning Agent – Task Decomposition', description: 'Breaks down a high-level requirement into...', version: 'v1.8', status: 'Published', icon: 'agents/planning-agent', updatedAt: '14 Nov 2026, 06:02 PM', owner: 'Aditya Jagtap', evalScore: 0.89,
      body: `You are a Planning Agent in the Software Factory.
Break the following requirement down into an ordered list of concrete, independently executable tasks.

### Context
- Project: {{project_name}}
- Repository: {{repository}}

### Instructions
1. Clarify the goal and constraints of the requirement.
2. Split it into the smallest set of sequential tasks that deliver it.
3. Note dependencies between tasks.
4. Flag anything that needs human approval before work starts.`
    },
    {
      id: 'PR-3', agent: 'Review Agent', name: 'Review Agent – Code Review', description: 'Reviews code for quality, security and best...', version: 'v2.1', status: 'Published', icon: 'agents/review-agent', updatedAt: '13 Nov 2026, 09:40 AM', owner: 'Aditya Jagtap', evalScore: 0.93,
      body: `You are a Review Agent in the Software Factory.
Review the diff for this task for correctness, security and maintainability.

### Context
- Project: {{project_name}}
- Repository: {{repository}}

### Instructions
1. Check the change against the stated requirement.
2. Flag correctness bugs, security issues and missing tests.
3. Flag anything that violates project coding standards.
4. Keep feedback specific and actionable, with file and line references.`
    },
    {
      id: 'PR-4', agent: 'QA Agent', name: 'QA Agent – Test Generation', description: 'Creates unit, integration and edge case tests...', version: 'v1.6', status: 'In Review', icon: 'agents/testing-agent', updatedAt: '12 Nov 2026, 03:15 PM', owner: 'Aditya Jagtap', evalScore: 0.86,
      body: `You are a QA Agent in the Software Factory.
Write tests for the change described below.

### Context
- Project: {{project_name}}
- Repository: {{repository}}

### Instructions
1. Cover the happy path and the realistic edge cases.
2. Add regression tests for any bug being fixed.
3. Use the project's existing test framework and conventions.
4. Report coverage gaps you could not close.`
    },
    {
      id: 'PR-5', agent: 'Documentation Agent', name: 'Documentation Agent', description: 'Generates technical and API documentation...', version: 'v1.4', status: 'Published', icon: 'agents/documentation-agent', updatedAt: '10 Nov 2026, 08:00 AM', owner: 'Aditya Jagtap', evalScore: 0.88,
      body: `You are a Documentation Agent in the Software Factory.
Write or update documentation for the change described below.

### Context
- Project: {{project_name}}
- Repository: {{repository}}

### Instructions
1. Update the README or relevant docs affected by the change.
2. Document new or changed APIs, configs and CLI flags.
3. Keep examples runnable and consistent with the current code.`
    },
    {
      id: 'PR-6', agent: 'Knowledge Agent', name: 'Knowledge Agent – RAG', description: 'Answers project and engineering queries usi...', version: 'v2.0', status: 'Published', icon: 'navigation/knowledge', updatedAt: '05 Nov 2026, 03:17 PM', owner: 'Aditya Jagtap', evalScore: 0.9,
      body: `You are a Knowledge Agent in the Software Factory.
Answer the question below using only real knowledge retrieved from this project's knowledge graph.

### Context
- Project: {{project_name}}
- Repository: {{repository}}

### Instructions
1. Retrieve relevant entities and relationships before answering.
2. Cite the files or nodes the answer is based on.
3. Say plainly when the knowledge graph has no answer, instead of guessing.`
    }
  ]);

  readonly providers = signal<ProviderConnection[]>([
    { id: 'p-openai', name: 'OpenAI', type: 'Cloud', status: 'Healthy', models: 4, lastChecked: '2 min ago', icon: 'providers/cloud-provider' },
    { id: 'p-anthropic', name: 'Anthropic (Claude)', type: 'Cloud', status: 'Healthy', models: 3, lastChecked: '3 min ago', icon: 'providers/cloud-provider' },
    { id: 'p-google', name: 'Google (Gemini)', type: 'Cloud', status: 'Healthy', models: 3, lastChecked: '2 min ago', icon: 'providers/cloud-provider' },
    { id: 'p-ollama', name: 'Ollama (Local)', type: 'Local', status: 'Healthy', models: 6, lastChecked: '1 min ago', icon: 'providers/local-model' },
    { id: 'p-qwen', name: 'Qwen', type: 'Local', status: 'Healthy', models: 2, lastChecked: '2 min ago', icon: 'providers/local-model' }
  ]);

  readonly modelCatalog = signal<ModelCatalogEntry[]>([
    { id: 'm1', model: 'claude-3-7-sonnet', provider: 'Anthropic', type: 'Chat', context: '200K', capabilities: ['Code', 'Reasoning', 'Tool Use'], status: 'Active' },
    { id: 'm2', model: 'gpt-5', provider: 'OpenAI', type: 'Chat', context: '400K', capabilities: ['Code', 'Reasoning', 'Vision'], status: 'Active' },
    { id: 'm3', model: 'gemini-2.5-pro', provider: 'Google', type: 'Chat', context: '1M', capabilities: ['Code', 'Reasoning', 'Vision'], status: 'Active' },
    { id: 'm4', model: 'qwen3:14b', provider: 'Qwen', type: 'Local', context: '128K', capabilities: ['Code', 'Chat'], status: 'Active' },
    { id: 'm5', model: 'llama3.1:8b', provider: 'Ollama', type: 'Local', context: '128K', capabilities: ['Code', 'Chat'], status: 'Active' }
  ]);

  readonly codingAgentRuntimes = signal<CodingAgentRuntime[]>([
    {
      id: 'codex', name: 'Codex', description: 'OpenAI coding-agent runtime via Codex SDK / App Server',
      icon: 'agents/coding-agent', connectionMode: 'Local runtime', authMethod: 'ChatGPT / API key',
      status: 'Connected', version: '0.42.1', lastHealthCheck: '2 min ago',
      capabilities: ['Start thread', 'Resume thread', 'Stream events', 'Run tests', 'Apply sandbox']
    },
    {
      id: 'claude-code', name: 'Claude Code', description: 'Anthropic coding-agent runtime via Claude Agent SDK / CLI',
      icon: 'agents/coding-agent', connectionMode: 'Local runtime', authMethod: 'Official CLI authentication',
      status: 'Connected', version: '2.1.0', lastHealthCheck: '2 min ago',
      capabilities: ['Start session', 'Resume session', 'Stream messages', 'Permission modes', 'Hooks']
    },
    {
      id: 'gemini-cli', name: 'Gemini CLI', description: 'Google coding-agent runtime',
      icon: 'agents/coding-agent', connectionMode: 'Local runtime', authMethod: 'Supported provider authentication',
      status: 'Not connected', capabilities: ['Start session', 'Stream events', 'Run tests']
    },
    {
      id: 'custom', name: 'Custom Agent', description: 'Adapter implementing the common Agent Runtime Interface',
      icon: 'navigation/providers', connectionMode: 'Custom adapter', authMethod: 'Configured credential',
      status: 'Not configured', capabilities: ['Depends on adapter']
    }
  ]);

  readonly monitoringAlerts = signal<MonitoringAlert[]>([
    { id: 'al1', severity: 'High', title: 'Task failure rate > 5%', detail: '3 tasks failed in the last 30 minutes', timestamp: '12 min ago' },
    { id: 'al2', severity: 'Medium', title: 'Slow execution detected', detail: 'Avg. time increased by 42% (Coding Agent)', timestamp: '37 min ago' },
    { id: 'al3', severity: 'Info', title: 'Provider quota at 80%', detail: 'OpenAI usage has reached 80% of daily limit', timestamp: '1 hr ago' }
  ]);

  readonly graphEntities = signal<GraphEntity[]>([
    { id: 'payment-service', label: 'PaymentService', type: 'Class • Java', icon: 'navigation/artifacts', tone: 'blue', x: 2, y: 1 },
    { id: 'payment-controller', label: 'PaymentController (Java)', type: 'Controller', icon: 'workspace/code-diff', tone: 'blue', x: 1, y: 0 },
    { id: 'req-128', label: 'REQ-128 Process invoice payments', type: 'Requirement', icon: 'navigation/artifacts', tone: 'amber', x: 2, y: 0 },
    { id: 'adr-014', label: 'ADR-014 Use event-driven payment processing', type: 'Decision', icon: 'navigation/workflows', tone: 'amber', x: 3, y: 0 },
    { id: 'invoice-service', label: 'invoice-service (Repository)', type: 'Repository', icon: 'navigation/repositories', tone: 'green', x: 0, y: 1 },
    { id: 'payment-gateway', label: 'PaymentGateway (Interface)', type: 'Interface', icon: 'workspace/code-diff', tone: 'blue', x: 3, y: 1 },
    { id: 'payment-service-test', label: 'PaymentServiceTest (Test)', type: 'Test', icon: 'agents/testing-agent', tone: 'green', x: 1, y: 2 },
    { id: 'payments-table', label: 'payments (Table)', type: 'Table', icon: 'navigation/repositories', tone: 'blue', x: 2, y: 2 },
    { id: 'api-payments', label: '/api/payments (API Endpoint)', type: 'Endpoint', icon: 'navigation/settings', tone: 'amber', x: 3, y: 2 }
  ]);

  readonly graphRelationships = signal<GraphRelationship[]>([
    { from: 'payment-controller', to: 'payment-service', label: 'CALLS' },
    { from: 'payment-service', to: 'req-128', label: 'IMPLEMENTS' },
    { from: 'payment-service', to: 'adr-014', label: 'RELATES_TO' },
    { from: 'invoice-service', to: 'payment-service', label: 'CONTAINS' },
    { from: 'payment-service', to: 'payment-gateway', label: 'DEPENDS_ON' },
    { from: 'payment-service', to: 'payment-service-test', label: 'TESTS' },
    { from: 'payment-service', to: 'payments-table', label: 'USES' },
    { from: 'payment-service', to: 'api-payments', label: 'EXPOSES' }
  ]);

  readonly repoTree = signal<RepoTreeNode>({
    name: 'fintrix-platform', type: 'folder',
    children: [
      {
        name: 'src/main/java/com/fintrix', type: 'folder', children: [
          { name: 'config', type: 'folder' },
          { name: 'controller', type: 'folder', children: [
            { name: 'InvoiceController.java', type: 'file' },
            { name: 'HealthController.java', type: 'file' }
          ] },
          { name: 'service', type: 'folder', children: [
            { name: 'InvoiceExtractionService.java', type: 'file', active: true },
            { name: 'DocumentParserService.java', type: 'file' },
            { name: 'ClassificationService.java', type: 'file' }
          ] },
          { name: 'repository', type: 'folder' },
          { name: 'model', type: 'folder' },
          { name: 'dto', type: 'folder' },
          { name: 'util', type: 'folder' }
        ]
      },
      { name: 'src/test/java', type: 'folder' },
      { name: 'pom.xml', type: 'file' },
      { name: 'README.md', type: 'file' }
    ]
  });
}
