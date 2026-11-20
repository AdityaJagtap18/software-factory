import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AuthService } from '../auth/auth.service';
import { ApiTask, CreateTaskPayload, MyApiTask, TaskDiff } from './task.models';

@Injectable({ providedIn: 'root' })
export class TaskService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  readonly tasks = signal<ApiTask[]>([]);
  readonly loaded = signal(false);
  readonly myTasks = signal<MyApiTask[]>([]);
  readonly myTasksLoaded = signal(false);

  private readonly watching = new Set<string>();

  listMine(): Observable<MyApiTask[]> {
    return this.http.get<MyApiTask[]>(`${environment.apiBaseUrl}/tasks/mine`).pipe(
      tap((tasks) => {
        this.myTasks.set(tasks);
        this.myTasksLoaded.set(true);
      })
    );
  }

  listForProject(projectId: string): Observable<ApiTask[]> {
    return this.http.get<ApiTask[]>(`${environment.apiBaseUrl}/projects/${projectId}/tasks`).pipe(
      tap((tasks) => {
        this.tasks.set(tasks);
        this.loaded.set(true);
        // A task someone else started is already running when this viewer
        // opens the page — watch it live too, not just the task's starter.
        for (const task of tasks) {
          if (task.status === 'running') this.watch(projectId, task.id);
        }
      })
    );
  }

  private watch(projectId: string, taskId: string): void {
    if (this.watching.has(taskId)) return;
    this.watching.add(taskId);
    void this.streamUntilDone(projectId, taskId).finally(() => this.watching.delete(taskId));
  }

  create(projectId: string, payload: CreateTaskPayload): Observable<ApiTask> {
    return this.http
      .post<ApiTask>(`${environment.apiBaseUrl}/projects/${projectId}/tasks`, payload)
      .pipe(tap((task) => this.tasks.update((list) => [task, ...list])));
  }

  private patchTask(taskId: string, patch: Partial<ApiTask>): void {
    this.tasks.update((list) => list.map((t) => (t.id === taskId ? { ...t, ...patch } : t)));
    this.myTasks.update((list) => list.map((t) => (t.id === taskId ? { ...t, ...patch } : t)));
  }

  /**
   * Starts a task, then live-streams its real status/output over SSE and
   * applies each genuine update to the local task list as it arrives — no
   * client-side progress simulation.
   */
  start(projectId: string, taskId: string): Observable<ApiTask> {
    return this.http
      .post<ApiTask>(`${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/start`, {})
      .pipe(
        tap((task) => {
          this.patchTask(taskId, task);
          this.watch(projectId, taskId);
        })
      );
  }

  cancel(projectId: string, taskId: string): Observable<ApiTask> {
    return this.http
      .post<ApiTask>(`${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/cancel`, {})
      .pipe(tap((task) => this.patchTask(taskId, task)));
  }

  /** The real diff this task's run produced inside its Git worktree
   * (Phase 14) — empty fields for a task with no repository connection or
   * no filesystem changes, never a fabricated one. */
  getDiff(projectId: string, taskId: string): Observable<TaskDiff> {
    return this.http.get<TaskDiff>(`${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/diff`);
  }

  private async streamUntilDone(projectId: string, taskId: string): Promise<void> {
    const token = this.auth.accessToken;
    const resp = await fetch(
      `${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/stream`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} }
    );
    if (!resp.ok || !resp.body) {
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const payload = JSON.parse(line.slice('data: '.length));
          this.patchTask(taskId, payload);
        } catch {
          // Malformed/partial chunk — skip rather than guess at its content.
        }
      }
    }
  }
}
