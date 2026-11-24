import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AgentConnection, CreateConnectionPayload, ModelCatalogResponse } from './agent-runtime.models';

@Injectable({ providedIn: 'root' })
export class AgentRuntimeService {
  private readonly http = inject(HttpClient);

  readonly connections = signal<AgentConnection[]>([]);
  readonly loaded = signal(false);

  listForOrg(orgId: string): Observable<AgentConnection[]> {
    return this.http
      .get<AgentConnection[]>(`${environment.apiBaseUrl}/organizations/${orgId}/coding-agent-connections`)
      .pipe(
        tap((connections) => {
          this.connections.set(connections);
          this.loaded.set(true);
        })
      );
  }

  connect(orgId: string, payload: CreateConnectionPayload): Observable<AgentConnection> {
    return this.http
      .post<AgentConnection>(
        `${environment.apiBaseUrl}/organizations/${orgId}/coding-agent-connections`,
        payload
      )
      .pipe(
        tap((connection) => {
          this.connections.update((list) =>
            list.map((c) => (c.runtime_slug === connection.runtime_slug ? connection : c))
          );
        })
      );
  }

  recheck(orgId: string, connectionId: string): Observable<AgentConnection> {
    return this.http
      .post<AgentConnection>(
        `${environment.apiBaseUrl}/organizations/${orgId}/coding-agent-connections/${connectionId}/health-check`,
        {}
      )
      .pipe(
        tap((connection) => {
          this.connections.update((list) =>
            list.map((c) => (c.runtime_slug === connection.runtime_slug ? connection : c))
          );
        })
      );
  }

  disconnect(orgId: string, connectionId: string, runtimeSlug: string): Observable<void> {
    return this.http
      .delete<void>(`${environment.apiBaseUrl}/organizations/${orgId}/coding-agent-connections/${connectionId}`)
      .pipe(
        tap(() => {
          this.connections.update((list) =>
            list.map((c) =>
              c.runtime_slug === runtimeSlug
                ? {
                    ...c,
                    id: null,
                    is_configured: false,
                    status: 'not_configured',
                    detected_version: '',
                    last_error: '',
                    last_health_check_at: null,
                    has_credential: false
                  }
                : c
            )
          );
        })
      );
  }

  getModelCatalog(projectId: string, taskId?: string): Observable<ModelCatalogResponse> {
    const url = `${environment.apiBaseUrl}/projects/${projectId}/agent-runtimes/model-catalog${taskId ? `?task_id=${taskId}` : ''}`;
    return this.http.get<ModelCatalogResponse>(url);
  }
}
