import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { IconComponent } from '../../shared/icon/icon.component';
import { TaskService } from '../../core/org/task.service';
import { TaskDiff } from '../../core/org/task.models';
import { DiffFile, parseUnifiedDiff } from '../../shared/diff/diff-parser';

@Component({
  selector: 'sf-task-workspace',
  standalone: true,
  imports: [RouterLink, IconComponent, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './task-workspace.component.html',
  styleUrl: './task-workspace.component.scss'
})
export class TaskWorkspaceComponent {
  private readonly taskService = inject(TaskService);
  private readonly route = inject(ActivatedRoute);

  private readonly params = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });

  readonly tasks = this.taskService.myTasks;
  readonly loaded = this.taskService.myTasksLoaded;

  readonly selectedTask = computed(() => {
    const list = this.tasks();
    if (list.length === 0) return null;
    const id = this.params()?.get('taskId');
    return list.find((t) => t.id === id) ?? list[0];
  });

  readonly startingTaskId = signal<string | null>(null);

  readonly showingDiff = signal(false);
  readonly loadingDiff = signal(false);
  readonly taskDiff = signal<TaskDiff | null>(null);
  readonly selectedDiffPath = signal<string | null>(null);

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

  constructor() {
    this.taskService.listMine().subscribe();
  }

  selectDiffFile(path: string): void {
    this.selectedDiffPath.set(path);
  }

  toggleDiff(): void {
    const task = this.selectedTask();
    if (!task) return;
    if (this.showingDiff()) {
      this.showingDiff.set(false);
      return;
    }
    this.showingDiff.set(true);
    this.loadingDiff.set(true);
    this.selectedDiffPath.set(null);
    this.taskService.getDiff(task.project_id, task.id).subscribe({
      next: (diff) => {
        this.taskDiff.set(diff);
        this.loadingDiff.set(false);
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

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'completed') return 'green';
    if (status === 'running') return 'blue';
    if (status === 'failed') return 'amber';
    return 'gray';
  }
}
