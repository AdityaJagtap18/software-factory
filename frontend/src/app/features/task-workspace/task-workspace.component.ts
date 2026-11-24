import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { IconComponent } from '../../shared/icon/icon.component';
import { TaskService } from '../../core/org/task.service';
import { ApiTask, TaskDiff, TaskMessage } from '../../core/org/task.models';
import { DiffFile, parseUnifiedDiff } from '../../shared/diff/diff-parser';
import { GitIntegrationService } from '../../core/org/git-integration.service';
import { ProjectService } from '../../core/org/project.service';
import { AgentRuntimeService } from '../../core/org/agent-runtime.service';
import { ApiProject } from '../../core/auth/auth.models';
import { AgentConnection, ModelOption } from '../../core/org/agent-runtime.models';
import { ModelPickerComponent } from '../../shared/model-picker/model-picker.component';
import { ReviewCommentService } from '../../core/org/review-comment.service';
import { ApiReviewComment } from '../../core/org/review-comment.models';
import { TestRunService } from '../../core/org/test-run.service';

export type TaskWorkspaceTab = 'conversation' | 'changes' | 'tests' | 'quality' | 'artifacts' | 'logs';

@Component({
  selector: 'sf-task-workspace',
  standalone: true,
  imports: [RouterLink, IconComponent, DatePipe, FormsModule, ModelPickerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './task-workspace.component.html',
  styleUrl: './task-workspace.component.scss'
})
export class TaskWorkspaceComponent {
  private readonly taskService = inject(TaskService);
  private readonly gitService = inject(GitIntegrationService);
  private readonly projectService = inject(ProjectService);
  private readonly runtimeService = inject(AgentRuntimeService);
  private readonly reviewCommentService = inject(ReviewCommentService);
  private readonly testRunService = inject(TestRunService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly params = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });

  readonly tasks = this.taskService.myTasks;
  readonly loaded = this.taskService.myTasksLoaded;
  readonly connections = this.runtimeService.connections;

  readonly currentProject = signal<ApiProject | null>(null);
  readonly projectTasks = signal<ApiTask[]>([]);
  readonly projectTaskSearch = signal('');
  readonly sidebarCollapsed = signal(false);
  readonly reassigningAgent = signal(false);

  readonly selectedTask = computed(() => {
    const list = this.tasks();
    if (list.length === 0) return null;
    const id = this.params()?.get('taskId');
    return list.find((t) => t.id === id) ?? list[0];
  });

  readonly filteredProjectTasks = computed(() => {
    const list = this.projectTasks();
    const query = this.projectTaskSearch().trim().toLowerCase();
    if (!query) return list;
    return list.filter(
      (t) =>
        t.title.toLowerCase().includes(query) ||
        t.id.toLowerCase().includes(query) ||
        (t.description && t.description.toLowerCase().includes(query))
    );
  });

  readonly assignedAgent = computed<AgentConnection | null>(() => {
    const task = this.selectedTask();
    if (!task?.coding_agent_connection_id) return null;
    return this.connections().find((c) => c.id === task.coding_agent_connection_id) ?? null;
  });

  readonly knowledgeStatus = computed(() => {
    const task = this.selectedTask();
    const kc = task?.knowledge_context;
    if (!kc || Object.keys(kc).length === 0) {
      return { status: 'pending', label: 'Consulted on task run', count: 0, files: 0, repo: '' };
    }
    if (kc['retrieved']) {
      const count = kc['total_entities'] ?? 0;
      const files = kc['files_count'] ?? 0;
      const repo = kc['repository_name'] ?? '';
      return { status: 'synced', label: `Synced (${count} entities, ${files} files)`, count, files, repo };
    }
    return { status: 'offline', label: kc['error'] ? `Unavailable: ${kc['error']}` : 'Graph Unavailable', count: 0, files: 0, repo: '' };
  });

  readonly displayId = computed(() => {
    const task = this.selectedTask();
    return task ? `TSK-${task.id.slice(0, 8)}` : '';
  });

  readonly startingTaskId = signal<string | null>(null);
  readonly mergingPr = signal(false);
  readonly mergePrError = signal('');

  readonly tab = signal<TaskWorkspaceTab>('conversation');

  readonly loadingDiff = signal(false);
  readonly taskDiff = signal<TaskDiff | null>(null);
  readonly selectedDiffPath = signal<string | null>(null);
  readonly diffExpanded = signal(false);
  readonly copiedPath = signal<string | null>(null);

  readonly comments = this.reviewCommentService.comments;
  readonly loadingComments = signal(false);
  readonly commentDraft = signal('');
  readonly submittingComment = signal(false);
  readonly resolvingCommentId = signal<string | null>(null);
  private loadedCommentsForTaskId: string | null = null;

  readonly testRuns = this.testRunService.runs;
  readonly loadingTestRuns = signal(false);
  readonly triggeringTestRun = signal(false);
  readonly testRunError = signal('');
  private loadedTestRunsForTaskId: string | null = null;

  readonly latestTestRun = computed(() => this.testRuns()[0] ?? null);

  readonly messages = signal<TaskMessage[]>([]);
  readonly loadingMessages = signal(false);
  readonly draft = signal('');
  readonly sendingMessage = signal(false);
  readonly selectedComposerModel = signal<string>('');
  readonly selectedExecutionRuntime = signal<string>('');

  readonly activeModelDisplay = computed(() => {
    const task = this.selectedTask();
    const model = this.selectedComposerModel() || task?.selected_model;
    if (!model) return '';
    if (model.includes(':')) {
      return model.split(':')[1];
    }
    return model;
  });

  onModelSelected(model: ModelOption): void {
    this.selectedComposerModel.set(model.id);
    this.selectedExecutionRuntime.set(model.runtime_slug);
    const task = this.selectedTask();
    if (task) {
      this.taskService
        .update(task.project_id, task.id, {
          selected_model: model.id,
          execution_runtime: model.runtime_slug,
          coding_agent_connection_id: model.connection_id
        })
        .subscribe();
    }
  }

  private loadedDiffForTaskId: string | null = null;
  private loadedMessagesForTaskId: string | null = null;

  readonly diffFiles = computed<DiffFile[]>(() => {
    const diff = this.taskDiff();
    return diff ? parseUnifiedDiff(diff.git_diff) : [];
  });

  readonly diffTotals = computed(() => {
    const files = this.diffFiles();
    return {
      files: files.length,
      additions: files.reduce((sum, f) => sum + f.additions, 0),
      deletions: files.reduce((sum, f) => sum + f.deletions, 0)
    };
  });

  readonly selectedDiffFile = computed<DiffFile | null>(() => {
    const files = this.diffFiles();
    if (files.length === 0) return null;
    const wanted = this.selectedDiffPath();
    return files.find((f) => f.path === wanted) ?? files[0];
  });

  private lastSeenStatus = new Map<string, string>();

  constructor() {
    this.taskService.listMine().subscribe();

    let lastLoadedProjectId: string | null = null;
    effect(() => {
      const task = this.selectedTask();
      if (!task) return;
      if (task.project_id !== lastLoadedProjectId) {
        lastLoadedProjectId = task.project_id;
        this.taskService.listForProject(task.project_id).subscribe((tasks) => this.projectTasks.set(tasks));
        this.projectService.get(task.project_id).subscribe((p) => {
          this.currentProject.set(p);
          this.runtimeService.listForOrg(p.organization_id).subscribe();
        });
      }
    });

    // Re-fetches conversation/diff data whenever the selected task or the
    // active tab changes, including when the task picker switches tasks
    // without a route navigation re-creating this component.
    effect(() => {
      const task = this.selectedTask();
      const tab = this.tab();
      if (!task) return;
      if (tab === 'conversation') this.ensureMessagesLoaded();
      if (tab === 'changes') {
        this.ensureDiffLoaded();
        this.ensureCommentsLoaded();
        this.ensureTestRunsLoaded();
      }
      if (tab === 'tests') this.ensureTestRunsLoaded();
    });

    // A follow-up run finishing (via the real SSE stream in TaskService)
    // flips task.status away from 'running' — that's the signal to refetch
    // the real agent reply and the updated diff, rather than polling.
    effect(() => {
      const task = this.selectedTask();
      if (!task) return;
      const prev = this.lastSeenStatus.get(task.id);
      this.lastSeenStatus.set(task.id, task.status);
      if (prev === 'running' && task.status !== 'running') {
        this.loadedMessagesForTaskId = null;
        this.loadedDiffForTaskId = null;
        this.loadedTestRunsForTaskId = null;
        if (this.tab() === 'conversation') this.ensureMessagesLoaded();
        if (this.tab() === 'changes') this.ensureDiffLoaded();
        if (this.tab() === 'tests') this.ensureTestRunsLoaded();
      }
    });
  }

  toggleSidebar(): void {
    this.sidebarCollapsed.update((v) => !v);
  }

  agentName(connectionId: string | null): string {
    if (!connectionId) return 'Unassigned';
    const conn = this.connections().find((c) => c.id === connectionId);
    return conn ? conn.runtime_name : 'Agent';
  }

  reassignTaskAgent(connectionId: string): void {
    const task = this.selectedTask();
    if (!task || task.status !== 'not_started' || this.reassigningAgent()) return;
    this.reassigningAgent.set(true);
    this.taskService
      .update(task.project_id, task.id, {
        coding_agent_connection_id: connectionId || null
      })
      .subscribe({
        next: () => this.reassigningAgent.set(false),
        error: () => this.reassigningAgent.set(false)
      });
  }

  selectTask(taskId: string): void {
    this.router.navigateByUrl(`/tasks/${taskId}`);
  }

  setTab(tab: TaskWorkspaceTab): void {
    this.tab.set(tab);
    if (tab === 'changes') {
      this.ensureDiffLoaded();
      this.ensureCommentsLoaded();
      this.ensureTestRunsLoaded();
    }
    if (tab === 'conversation') this.ensureMessagesLoaded();
    if (tab === 'tests') this.ensureTestRunsLoaded();
  }

  private ensureMessagesLoaded(): void {
    const task = this.selectedTask();
    if (!task) return;
    if (this.loadedMessagesForTaskId === task.id) return;
    this.loadingMessages.set(true);
    this.taskService.listMessages(task.project_id, task.id).subscribe({
      next: (messages) => {
        this.messages.set(messages);
        this.loadingMessages.set(false);
        this.loadedMessagesForTaskId = task.id;
      },
      error: () => this.loadingMessages.set(false)
    });
  }

  sendMessage(): void {
    const task = this.selectedTask();
    const content = this.draft().trim();
    if (!task || !content || this.sendingMessage()) return;
    this.sendingMessage.set(true);
    const chosenModel = this.selectedComposerModel() || task.selected_model;
    this.taskService.sendMessage(task.project_id, task.id, content, chosenModel).subscribe({
      next: (message) => {
        this.messages.update((list) => [...list, message]);
        this.draft.set('');
        this.sendingMessage.set(false);
        // The run itself streams into task.output via the same SSE watch
        // `sendMessage()` kicked off; once it lands, the diff tab's data
        // should be re-fetched rather than reused from before this turn.
        this.loadedDiffForTaskId = null;
      },
      error: (err: { error?: { detail?: string } }) => {
        this.sendingMessage.set(false);
        this.messages.update((list) => [
          ...list,
          {
            id: `local-error-${Date.now()}`,
            task_id: task.id,
            role: 'system',
            content: err?.error?.detail ?? 'Could not send this message.',
            created_at: new Date().toISOString()
          }
        ]);
      }
    });
  }

  selectDiffFile(path: string): void {
    this.selectedDiffPath.set(path);
  }

  toggleDiffExpanded(): void {
    this.diffExpanded.update((v) => !v);
  }

  copyDiff(file: DiffFile): void {
    navigator.clipboard?.writeText(file.raw).then(
      () => {
        this.copiedPath.set(file.path);
        setTimeout(() => this.copiedPath.set(null), 1500);
      },
      () => {}
    );
  }

  private ensureDiffLoaded(): void {
    const task = this.selectedTask();
    if (!task) return;
    if (this.loadedDiffForTaskId === task.id) return;
    this.loadingDiff.set(true);
    this.selectedDiffPath.set(null);
    this.taskService.getDiff(task.project_id, task.id).subscribe({
      next: (diff) => {
        this.taskDiff.set(diff);
        this.loadingDiff.set(false);
        this.loadedDiffForTaskId = task.id;
      },
      error: () => this.loadingDiff.set(false)
    });
  }

  private ensureCommentsLoaded(): void {
    const task = this.selectedTask();
    if (!task) return;
    if (this.loadedCommentsForTaskId === task.id) return;
    this.loadingComments.set(true);
    this.reviewCommentService.listForTask(task.project_id, task.id).subscribe({
      next: () => {
        this.loadingComments.set(false);
        this.loadedCommentsForTaskId = task.id;
      },
      error: () => this.loadingComments.set(false)
    });
  }

  submitComment(): void {
    const task = this.selectedTask();
    const body = this.commentDraft().trim();
    if (!task || !body || this.submittingComment()) return;
    this.submittingComment.set(true);
    const file = this.selectedDiffFile();
    this.reviewCommentService
      .create(task.project_id, task.id, { body, file_path: file?.path ?? '' })
      .subscribe({
        next: () => {
          this.commentDraft.set('');
          this.submittingComment.set(false);
        },
        error: () => this.submittingComment.set(false)
      });
  }

  resolveComment(comment: ApiReviewComment): void {
    const task = this.selectedTask();
    if (!task || this.resolvingCommentId()) return;
    this.resolvingCommentId.set(comment.id);
    this.reviewCommentService.resolve(task.project_id, task.id, comment.id).subscribe({
      next: () => this.resolvingCommentId.set(null),
      error: () => this.resolvingCommentId.set(null)
    });
  }

  private ensureTestRunsLoaded(): void {
    const task = this.selectedTask();
    if (!task) return;
    if (this.loadedTestRunsForTaskId === task.id) return;
    this.loadingTestRuns.set(true);
    this.testRunService.listForTask(task.project_id, task.id).subscribe({
      next: () => {
        this.loadingTestRuns.set(false);
        this.loadedTestRunsForTaskId = task.id;
      },
      error: () => this.loadingTestRuns.set(false)
    });
  }

  triggerTestRun(): void {
    const task = this.selectedTask();
    if (!task || this.triggeringTestRun()) return;
    this.triggeringTestRun.set(true);
    this.testRunError.set('');
    this.testRunService.trigger(task.project_id, task.id).subscribe({
      next: () => this.triggeringTestRun.set(false),
      error: (err) => {
        this.triggeringTestRun.set(false);
        this.testRunError.set(err?.error?.detail || 'Could not run tests for this task.');
      }
    });
  }

  start(): void {
    const task = this.selectedTask();
    if (!task) return;
    this.startingTaskId.set(task.id);
    this.taskService.start(task.project_id, task.id).subscribe({
      complete: () => this.startingTaskId.set(null),
      error: () => this.startingTaskId.set(null)
    });
  }

  cancel(): void {
    const task = this.selectedTask();
    if (!task) return;
    this.taskService.cancel(task.project_id, task.id).subscribe();
  }

  mergePr(): void {
    const task = this.selectedTask();
    if (!task || this.mergingPr()) return;
    this.mergingPr.set(true);
    this.mergePrError.set('');
    this.gitService.mergePullRequest(task.project_id, task.id).subscribe({
      next: (result) => {
        this.mergingPr.set(false);
        if (result.merged) {
          this.taskService.markPrMerged(task.id);
        } else {
          this.mergePrError.set(result.message || 'GitHub did not merge this pull request.');
        }
      },
      error: (err) => {
        this.mergingPr.set(false);
        this.mergePrError.set(err?.error?.detail ?? 'Could not merge this pull request.');
      }
    });
  }

  messageAvatar(role: string): string {
    // Built in TS, not inline in the template: a literal "</" substring in
    // template markup is parsed as a closing tag by Angular's compiler
    // even inside a `{{ }}` string, which breaks the whole template.
    if (role === 'user') return 'U';
    if (role === 'agent') return String.fromCharCode(60) + String.fromCharCode(47) + '>';
    return '!';
  }

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'completed') return 'green';
    if (status === 'running') return 'blue';
    if (status === 'failed') return 'amber';
    return 'gray';
  }
}
