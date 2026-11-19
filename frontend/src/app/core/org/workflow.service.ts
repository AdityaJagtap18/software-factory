import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AuthService } from '../auth/auth.service';
import { ApiWorkflow, CreateWorkflowPayload } from './workflow.models';

@Injectable({ providedIn: 'root' })
export class WorkflowService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  readonly workflows = signal<ApiWorkflow[]>([]);
  readonly loaded = signal(false);

  private readonly watching = new Set<string>();

  listForProject(projectId: string): Observable<ApiWorkflow[]> {
    return this.http.get<ApiWorkflow[]>(`${environment.apiBaseUrl}/projects/${projectId}/workflows`).pipe(
      tap((workflows) => {
        this.workflows.set(workflows);
        this.loaded.set(true);
        // A workflow someone else started is already running when this
        // viewer opens the page — watch it live too, not just its starter.
        for (const workflow of workflows) {
          if (workflow.status === 'running') this.watch(projectId, workflow.id);
        }
      })
    );
  }

  private watch(projectId: string, workflowId: string): void {
    if (this.watching.has(workflowId)) return;
    this.watching.add(workflowId);
    void this.streamUntilDone(projectId, workflowId).finally(() => this.watching.delete(workflowId));
  }

  create(projectId: string, payload: CreateWorkflowPayload): Observable<ApiWorkflow> {
    return this.http
      .post<ApiWorkflow>(`${environment.apiBaseUrl}/projects/${projectId}/workflows`, payload)
      .pipe(tap((workflow) => this.workflows.update((list) => [workflow, ...list])));
  }

  private patchWorkflow(workflowId: string, patch: Partial<ApiWorkflow>): void {
    this.workflows.update((list) => list.map((w) => (w.id === workflowId ? { ...w, ...patch } : w)));
  }

  /**
   * Starts a workflow, then live-streams its real status/step progress over
   * SSE and applies each genuine update to the local list as it arrives —
   * no client-side progress simulation.
   */
  start(projectId: string, workflowId: string): Observable<ApiWorkflow> {
    return this.http
      .post<ApiWorkflow>(`${environment.apiBaseUrl}/projects/${projectId}/workflows/${workflowId}/start`, {})
      .pipe(
        tap((workflow) => {
          this.patchWorkflow(workflowId, workflow);
          this.watch(projectId, workflowId);
        })
      );
  }

  cancel(projectId: string, workflowId: string): Observable<ApiWorkflow> {
    return this.http
      .post<ApiWorkflow>(`${environment.apiBaseUrl}/projects/${projectId}/workflows/${workflowId}/cancel`, {})
      .pipe(tap((workflow) => this.patchWorkflow(workflowId, workflow)));
  }

  private async streamUntilDone(projectId: string, workflowId: string): Promise<void> {
    const token = this.auth.accessToken;
    const resp = await fetch(
      `${environment.apiBaseUrl}/projects/${projectId}/workflows/${workflowId}/stream`,
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
          this.patchWorkflow(workflowId, {
            status: payload.status,
            current_step_index: payload.current_step_index,
            started_at: payload.started_at,
            completed_at: payload.completed_at,
            steps: this.mergeSteps(workflowId, payload.steps)
          });
        } catch {
          // Malformed/partial chunk — skip rather than guess at its content.
        }
      }
    }
  }

  private mergeSteps(workflowId: string, streamedSteps: Array<{ id: string; status: string; output: string; error_message: string }>): any {
    const current = this.workflows().find((w) => w.id === workflowId);
    if (!current) return [];
    return current.steps.map((step) => {
      const update = streamedSteps.find((s) => s.id === step.id);
      return update ? { ...step, status: update.status, output: update.output, error_message: update.error_message } : step;
    });
  }
}
