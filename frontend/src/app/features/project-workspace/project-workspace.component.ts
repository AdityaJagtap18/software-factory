import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnDestroy, computed, effect, inject, signal } from '@angular/core';
import { RouterLink, ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';
import { ProjectService } from '../../core/org/project.service';
import { TaskService } from '../../core/org/task.service';
import { AgentRuntimeService } from '../../core/org/agent-runtime.service';
import { WorkflowService } from '../../core/org/workflow.service';
import { PresenceService } from '../../core/org/presence.service';
import { KnowledgeService } from '../../core/org/knowledge.service';
import { GitIntegrationService } from '../../core/org/git-integration.service';
import { RepositorySummary } from '../../core/org/git-integration.models';
import { ApiProject } from '../../core/auth/auth.models';
import { ApiTask, TaskDiff } from '../../core/org/task.models';
import { ApiWorkflow, CreateWorkflowStepPayload } from '../../core/org/workflow.models';

type TabId = 'overview' | 'tasks' | 'workflows' | 'agents' | 'knowledge' | 'artifacts' | 'activity' | 'settings';

@Component({
  selector: 'sf-project-workspace',
  standalone: true,
  imports: [RouterLink, IconComponent, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './project-workspace.component.html',
  styleUrl: './project-workspace.component.scss'
})
export class ProjectWorkspaceComponent implements OnDestroy {
  private readonly data = inject(MockDataService);
  private readonly route = inject(ActivatedRoute);
  private readonly projectService = inject(ProjectService);
  private readonly taskService = inject(TaskService);
  private readonly runtimeService = inject(AgentRuntimeService);
  private readonly workflowService = inject(WorkflowService);
  private readonly presenceService = inject(PresenceService);
  private readonly knowledgeService = inject(KnowledgeService);
  private readonly gitService = inject(GitIntegrationService);

  private readonly projectId = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });

  readonly project = signal<ApiProject | null>(null);
  readonly loading = signal(true);
  readonly notFound = signal(false);

  readonly tasks = this.taskService.tasks;
  readonly tasksLoaded = this.taskService.loaded;
  readonly connections = this.runtimeService.connections;
  readonly viewers = this.presenceService.viewers;
  readonly knowledgeGraph = this.knowledgeService.graph;
  readonly syncingKnowledge = signal(false);
  readonly codeGraph = this.knowledgeService.codeGraph;
  readonly ingestPath = signal('');
  readonly ingestingRepository = signal(false);
  readonly ingestError = signal('');

  readonly gitInstallations = this.gitService.installations;
  readonly repositoryConnections = this.gitService.repositoryConnections;
  readonly repositoryConnectionsLoaded = this.gitService.repositoryConnectionsLoaded;
  readonly showConnectRepository = signal(false);
  readonly connectRepoInstallationId = signal('');
  readonly availableRepositories = signal<RepositorySummary[]>([]);
  readonly loadingRepositories = signal(false);
  readonly selectedRepositoryFullName = signal('');
  readonly connectingRepository = signal(false);
  readonly repoConnectError = signal('');
  readonly syncingConnectionId = signal<string | null>(null);

  readonly showCreateTask = signal(false);
  readonly newTaskTitle = signal('');
  readonly newTaskDescription = signal('');
  readonly newTaskConnectionId = signal('');
  readonly creatingTask = signal(false);
  readonly startingTaskId = signal<string | null>(null);

  readonly expandedDiffTaskId = signal<string | null>(null);
  readonly loadingDiffTaskId = signal<string | null>(null);
  readonly taskDiff = signal<TaskDiff | null>(null);

  readonly workflows = this.workflowService.workflows;
  readonly workflowsLoaded = this.workflowService.loaded;

  readonly showCreateWorkflow = signal(false);
  readonly newWorkflowName = signal('');
  readonly newWorkflowDescription = signal('');
  readonly newWorkflowSteps = signal<CreateWorkflowStepPayload[]>([{ title: '', coding_agent_connection_id: null }]);
  readonly creatingWorkflow = signal(false);
  readonly startingWorkflowId = signal<string | null>(null);

  /**
   * Agents aren't backend-owned yet (a later phase of the execution spec),
   * so that tab keeps showing illustrative mock data until that lands.
   */
  readonly agents = this.data.agents;
  readonly recentActivity = this.data.recentActivity;

  readonly tabs: { id: TabId; label: string; icon: string }[] = [
    { id: 'overview', label: 'Overview', icon: 'navigation/dashboard' },
    { id: 'tasks', label: 'Tasks', icon: 'navigation/tasks' },
    { id: 'workflows', label: 'Workflows', icon: 'navigation/workflows' },
    { id: 'agents', label: 'Agents', icon: 'navigation/agents' },
    { id: 'knowledge', label: 'Knowledge', icon: 'navigation/knowledge' },
    { id: 'artifacts', label: 'Artifacts', icon: 'navigation/artifacts' },
    { id: 'activity', label: 'Activity', icon: 'navigation/monitoring' },
    { id: 'settings', label: 'Settings', icon: 'navigation/settings' }
  ];

  activeTab = signal<TabId>('overview');

  constructor() {
    effect(() => {
      const id = this.projectId()?.get('projectId');
      if (!id) return;
      this.loading.set(true);
      this.notFound.set(false);
      this.projectService.get(id).subscribe({
        next: (project) => {
          this.project.set(project);
          this.loading.set(false);
          this.taskService.listForProject(project.id).subscribe();
          this.runtimeService.listForOrg(project.organization_id).subscribe();
          this.workflowService.listForProject(project.id).subscribe();
          this.presenceService.watch(project.id);
          this.knowledgeService.fetchGraph(project.id).subscribe();
          this.knowledgeService.fetchCodeGraph(project.id).subscribe();
          this.gitService.listInstallations(project.organization_id).subscribe();
          this.gitService.listRepositoryConnections(project.id).subscribe();
        },
        error: () => {
          this.notFound.set(true);
          this.loading.set(false);
        }
      });
    });
  }

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' | 'red' {
    if (status === 'Completed' || status === 'Active' || status === 'Success' || status === 'completed') return 'green';
    if (status === 'In Progress' || status === 'running') return 'blue';
    if (status === 'Pending Review') return 'amber';
    if (status === 'failed') return 'red';
    return 'gray';
  }

  taskStatusLabel(status: string): string {
    switch (status) {
      case 'not_started': return 'Not started';
      case 'running': return 'Running';
      case 'completed': return 'Completed';
      case 'failed': return 'Failed';
      default: return status;
    }
  }

  openCreateTask() {
    this.newTaskTitle.set('');
    this.newTaskDescription.set('');
    this.newTaskConnectionId.set('');
    this.showCreateTask.set(true);
  }

  closeCreateTask() {
    this.showCreateTask.set(false);
  }

  submitCreateTask() {
    const project = this.project();
    const title = this.newTaskTitle().trim();
    if (!project || !title) return;
    this.creatingTask.set(true);
    this.taskService
      .create(project.id, {
        title,
        description: this.newTaskDescription().trim(),
        coding_agent_connection_id: this.newTaskConnectionId() || null
      })
      .subscribe({
        next: () => {
          this.creatingTask.set(false);
          this.showCreateTask.set(false);
        },
        error: () => this.creatingTask.set(false)
      });
  }

  startTask(task: ApiTask) {
    const project = this.project();
    if (!project) return;
    this.startingTaskId.set(task.id);
    this.taskService.start(project.id, task.id).subscribe({
      complete: () => this.startingTaskId.set(null),
      error: () => this.startingTaskId.set(null)
    });
  }

  cancelTask(task: ApiTask) {
    const project = this.project();
    if (!project) return;
    this.taskService.cancel(project.id, task.id).subscribe();
  }

  toggleDiff(task: ApiTask) {
    if (this.expandedDiffTaskId() === task.id) {
      this.expandedDiffTaskId.set(null);
      this.taskDiff.set(null);
      return;
    }
    const project = this.project();
    if (!project) return;
    this.expandedDiffTaskId.set(task.id);
    this.taskDiff.set(null);
    this.loadingDiffTaskId.set(task.id);
    this.taskService.getDiff(project.id, task.id).subscribe({
      next: (diff) => {
        this.taskDiff.set(diff);
        this.loadingDiffTaskId.set(null);
      },
      error: () => this.loadingDiffTaskId.set(null)
    });
  }

  workflowStatusLabel(status: string): string {
    return this.taskStatusLabel(status);
  }

  openCreateWorkflow() {
    this.newWorkflowName.set('');
    this.newWorkflowDescription.set('');
    this.newWorkflowSteps.set([{ title: '', coding_agent_connection_id: null }]);
    this.showCreateWorkflow.set(true);
  }

  closeCreateWorkflow() {
    this.showCreateWorkflow.set(false);
  }

  addWorkflowStep() {
    this.newWorkflowSteps.update((steps) => [...steps, { title: '', coding_agent_connection_id: null }]);
  }

  removeWorkflowStep(index: number) {
    this.newWorkflowSteps.update((steps) => steps.filter((_, i) => i !== index));
  }

  updateWorkflowStepTitle(index: number, title: string) {
    this.newWorkflowSteps.update((steps) => steps.map((s, i) => (i === index ? { ...s, title } : s)));
  }

  updateWorkflowStepConnection(index: number, connectionId: string) {
    this.newWorkflowSteps.update((steps) =>
      steps.map((s, i) => (i === index ? { ...s, coding_agent_connection_id: connectionId || null } : s))
    );
  }

  submitCreateWorkflow() {
    const project = this.project();
    const name = this.newWorkflowName().trim();
    const steps = this.newWorkflowSteps()
      .map((s) => ({ ...s, title: s.title.trim() }))
      .filter((s) => s.title.length > 0);
    if (!project || !name || steps.length === 0) return;
    this.creatingWorkflow.set(true);
    this.workflowService
      .create(project.id, { name, description: this.newWorkflowDescription().trim(), steps })
      .subscribe({
        next: () => {
          this.creatingWorkflow.set(false);
          this.showCreateWorkflow.set(false);
        },
        error: () => this.creatingWorkflow.set(false)
      });
  }

  startWorkflow(workflow: ApiWorkflow) {
    const project = this.project();
    if (!project) return;
    this.startingWorkflowId.set(workflow.id);
    this.workflowService.start(project.id, workflow.id).subscribe({
      complete: () => this.startingWorkflowId.set(null),
      error: () => this.startingWorkflowId.set(null)
    });
  }

  cancelWorkflow(workflow: ApiWorkflow) {
    const project = this.project();
    if (!project) return;
    this.workflowService.cancel(project.id, workflow.id).subscribe();
  }

  syncKnowledge() {
    const project = this.project();
    if (!project) return;
    this.syncingKnowledge.set(true);
    this.knowledgeService.sync(project.id).subscribe({
      complete: () => this.syncingKnowledge.set(false),
      error: () => this.syncingKnowledge.set(false)
    });
  }

  nodeLabel(nodeId: string): string {
    const node = this.knowledgeGraph()?.nodes.find((n) => n.id === nodeId);
    return node?.label ?? nodeId;
  }

  ingestRepository() {
    const project = this.project();
    const path = this.ingestPath().trim();
    if (!project || !path) return;
    this.ingestingRepository.set(true);
    this.ingestError.set('');
    this.knowledgeService.ingestRepository(project.id, path).subscribe({
      next: (result) => {
        if (!result.connected) this.ingestError.set(result.detail);
        this.ingestingRepository.set(false);
      },
      error: (err) => {
        this.ingestError.set(err?.error?.detail ?? 'Failed to ingest repository.');
        this.ingestingRepository.set(false);
      }
    });
  }

  repoStatusTone(status: string): 'green' | 'amber' | 'red' | 'gray' {
    if (status === 'connected') return 'green';
    if (status === 'not_connected') return 'amber';
    if (status === 'error') return 'red';
    return 'gray';
  }

  repoStatusLabel(status: string): string {
    switch (status) {
      case 'connected': return 'Connected';
      case 'not_connected': return 'Not connected';
      case 'error': return 'Error';
      default: return status;
    }
  }

  openConnectRepository() {
    this.connectRepoInstallationId.set(this.gitInstallations()[0]?.id ?? '');
    this.availableRepositories.set([]);
    this.selectedRepositoryFullName.set('');
    this.repoConnectError.set('');
    this.showConnectRepository.set(true);
    if (this.connectRepoInstallationId()) this.loadRepositoriesForInstallation();
  }

  closeConnectRepository() {
    this.showConnectRepository.set(false);
  }

  onConnectRepoInstallationChange(installationId: string) {
    this.connectRepoInstallationId.set(installationId);
    this.selectedRepositoryFullName.set('');
    this.loadRepositoriesForInstallation();
  }

  private loadRepositoriesForInstallation() {
    const project = this.project();
    const installationId = this.connectRepoInstallationId();
    if (!project || !installationId) return;
    this.loadingRepositories.set(true);
    this.repoConnectError.set('');
    this.gitService.listInstallationRepositories(project.organization_id, installationId).subscribe({
      next: (repos) => {
        this.availableRepositories.set(repos);
        this.loadingRepositories.set(false);
      },
      error: (err) => {
        this.availableRepositories.set([]);
        this.loadingRepositories.set(false);
        this.repoConnectError.set(err?.error?.detail ?? 'Could not list repositories for this installation.');
      }
    });
  }

  submitConnectRepository() {
    const project = this.project();
    const installationId = this.connectRepoInstallationId();
    const repo = this.availableRepositories().find((r) => r.full_name === this.selectedRepositoryFullName());
    if (!project || !installationId || !repo) return;
    this.connectingRepository.set(true);
    this.repoConnectError.set('');
    this.gitService
      .createRepositoryConnection(project.id, {
        git_installation_id: installationId,
        owner: repo.owner,
        name: repo.name
      })
      .subscribe({
        next: () => {
          this.connectingRepository.set(false);
          this.showConnectRepository.set(false);
        },
        error: (err) => {
          this.connectingRepository.set(false);
          this.repoConnectError.set(err?.error?.detail ?? 'Could not connect this repository.');
        }
      });
  }

  syncRepositoryConnection(connectionId: string) {
    const project = this.project();
    if (!project) return;
    this.syncingConnectionId.set(connectionId);
    this.gitService.syncRepositoryConnection(project.id, connectionId).subscribe({
      complete: () => this.syncingConnectionId.set(null),
      error: () => this.syncingConnectionId.set(null)
    });
  }

  disconnectRepositoryConnection(connectionId: string) {
    const project = this.project();
    if (!project) return;
    this.gitService.deleteRepositoryConnection(project.id, connectionId).subscribe();
  }

  ngOnDestroy(): void {
    this.presenceService.stop();
  }
}
