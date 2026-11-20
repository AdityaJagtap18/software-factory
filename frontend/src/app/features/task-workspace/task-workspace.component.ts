import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { IconComponent } from '../../shared/icon/icon.component';
import { TaskService } from '../../core/org/task.service';
import { TaskDiff, TaskMessage } from '../../core/org/task.models';
import { DiffFile, parseUnifiedDiff } from '../../shared/diff/diff-parser';
import { GitIntegrationService } from '../../core/org/git-integration.service';

export type TaskWorkspaceTab = 'conversation' | 'changes' | 'tests' | 'quality' | 'artifacts' | 'logs';

@Component({
  selector: 'sf-task-workspace',
  standalone: true,
  imports: [RouterLink, IconComponent, DatePipe, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './task-workspace.component.html',
  styleUrl: './task-workspace.component.scss'
})
export class TaskWorkspaceComponent {
  private readonly taskService = inject(TaskService);
  private readonly gitService = inject(GitIntegrationService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly params = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });

  readonly tasks = this.taskService.myTasks;
  readonly loaded = this.taskService.myTasksLoaded;

  readonly selectedTask = computed(() => {
    const list = this.tasks();
    if (list.length === 0) return null;
    const id = this.params()?.get('taskId');
    return list.find((t) => t.id === id) ?? list[0];
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

  readonly messages = signal<TaskMessage[]>([]);
  readonly loadingMessages = signal(false);
  readonly draft = signal('');
  readonly sendingMessage = signal(false);

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

    // Re-fetches conversation/diff data whenever the selected task or the
    // active tab changes, including when the task picker switches tasks
    // without a route navigation re-creating this component.
    effect(() => {
      const task = this.selectedTask();
      const tab = this.tab();
      if (!task) return;
      if (tab === 'conversation') this.ensureMessagesLoaded();
      if (tab === 'changes') this.ensureDiffLoaded();
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
        if (this.tab() === 'conversation') this.ensureMessagesLoaded();
        if (this.tab() === 'changes') this.ensureDiffLoaded();
      }
    });
  }

  selectTask(taskId: string): void {
    this.router.navigateByUrl(`/tasks/${taskId}`);
  }

  setTab(tab: TaskWorkspaceTab): void {
    this.tab.set(tab);
    if (tab === 'changes') this.ensureDiffLoaded();
    if (tab === 'conversation') this.ensureMessagesLoaded();
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
    this.taskService.sendMessage(task.project_id, task.id, content).subscribe({
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
