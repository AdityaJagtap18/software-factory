import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiProject } from '../auth/auth.models';

@Injectable({ providedIn: 'root' })
export class ProjectService {
  private readonly http = inject(HttpClient);

  readonly projects = signal<ApiProject[]>([]);
  readonly loaded = signal(false);

  listForOrg(orgId: string): Observable<ApiProject[]> {
    return this.http
      .get<ApiProject[]>(`${environment.apiBaseUrl}/organizations/${orgId}/projects`)
      .pipe(
        tap((projects) => {
          this.projects.set(projects);
          this.loaded.set(true);
        })
      );
  }

  create(orgId: string, payload: { name: string; description?: string; repository_url?: string }): Observable<ApiProject> {
    return this.http
      .post<ApiProject>(`${environment.apiBaseUrl}/organizations/${orgId}/projects`, payload)
      .pipe(tap((project) => this.projects.update((list) => [...list, project])));
  }

  get(projectId: string): Observable<ApiProject> {
    return this.http.get<ApiProject>(`${environment.apiBaseUrl}/projects/${projectId}`);
  }
}
