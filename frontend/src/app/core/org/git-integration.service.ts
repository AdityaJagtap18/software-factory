import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import {
  CreateGitInstallationPayload,
  CreateRepositoryConnectionPayload,
  GitInstallation,
  RepositoryConnection,
  RepositorySummary
} from './git-integration.models';

@Injectable({ providedIn: 'root' })
export class GitIntegrationService {
  private readonly http = inject(HttpClient);

  readonly installations = signal<GitInstallation[]>([]);
  readonly installationsLoaded = signal(false);
  readonly repositoryConnections = signal<RepositoryConnection[]>([]);
  readonly repositoryConnectionsLoaded = signal(false);

  listInstallations(orgId: string): Observable<GitInstallation[]> {
    return this.http
      .get<GitInstallation[]>(`${environment.apiBaseUrl}/organizations/${orgId}/git-installations`)
      .pipe(
        tap((installations) => {
          this.installations.set(installations);
          this.installationsLoaded.set(true);
        })
      );
  }

  createInstallation(orgId: string, payload: CreateGitInstallationPayload): Observable<GitInstallation> {
    return this.http
      .post<GitInstallation>(`${environment.apiBaseUrl}/organizations/${orgId}/git-installations`, payload)
      .pipe(tap((installation) => this.installations.update((list) => [installation, ...list])));
  }

  recheckInstallation(orgId: string, installationId: string): Observable<GitInstallation> {
    return this.http
      .post<GitInstallation>(
        `${environment.apiBaseUrl}/organizations/${orgId}/git-installations/${installationId}/health-check`,
        {}
      )
      .pipe(
        tap((installation) => {
          this.installations.update((list) => list.map((i) => (i.id === installation.id ? installation : i)));
        })
      );
  }

  revokeInstallation(orgId: string, installationId: string): Observable<void> {
    return this.http
      .delete<void>(`${environment.apiBaseUrl}/organizations/${orgId}/git-installations/${installationId}`)
      .pipe(tap(() => this.installations.update((list) => list.filter((i) => i.id !== installationId))));
  }

  listInstallationRepositories(orgId: string, installationId: string): Observable<RepositorySummary[]> {
    return this.http.get<RepositorySummary[]>(
      `${environment.apiBaseUrl}/organizations/${orgId}/git-installations/${installationId}/repositories`
    );
  }

  listRepositoryConnections(projectId: string): Observable<RepositoryConnection[]> {
    return this.http
      .get<RepositoryConnection[]>(`${environment.apiBaseUrl}/projects/${projectId}/repository-connections`)
      .pipe(
        tap((connections) => {
          this.repositoryConnections.set(connections);
          this.repositoryConnectionsLoaded.set(true);
        })
      );
  }

  createRepositoryConnection(
    projectId: string,
    payload: CreateRepositoryConnectionPayload
  ): Observable<RepositoryConnection> {
    return this.http
      .post<RepositoryConnection>(`${environment.apiBaseUrl}/projects/${projectId}/repository-connections`, payload)
      .pipe(tap((connection) => this.repositoryConnections.update((list) => [connection, ...list])));
  }

  deleteRepositoryConnection(projectId: string, connectionId: string): Observable<void> {
    return this.http
      .delete<void>(`${environment.apiBaseUrl}/projects/${projectId}/repository-connections/${connectionId}`)
      .pipe(
        tap(() =>
          this.repositoryConnections.update((list) => list.filter((c) => c.id !== connectionId))
        )
      );
  }

  syncRepositoryConnection(projectId: string, connectionId: string): Observable<RepositoryConnection> {
    return this.http
      .post<RepositoryConnection>(
        `${environment.apiBaseUrl}/projects/${projectId}/repository-connections/${connectionId}/sync`,
        {}
      )
      .pipe(
        tap((connection) => {
          this.repositoryConnections.update((list) =>
            list.map((c) => (c.id === connection.id ? connection : c))
          );
        })
      );
  }
}
