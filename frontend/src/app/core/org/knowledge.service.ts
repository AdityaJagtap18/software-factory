import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import {
  CodeGraphResponse,
  IngestRepositoryResponse,
  KnowledgeGraphResponse,
  KnowledgeSyncResponse
} from './knowledge.models';

@Injectable({ providedIn: 'root' })
export class KnowledgeService {
  private readonly http = inject(HttpClient);

  readonly graph = signal<KnowledgeGraphResponse | null>(null);
  readonly codeGraph = signal<CodeGraphResponse | null>(null);

  sync(projectId: string): Observable<KnowledgeSyncResponse> {
    return this.http
      .post<KnowledgeSyncResponse>(`${environment.apiBaseUrl}/projects/${projectId}/knowledge/sync`, {})
      .pipe(tap(() => this.fetchGraph(projectId).subscribe()));
  }

  fetchGraph(projectId: string): Observable<KnowledgeGraphResponse> {
    return this.http
      .get<KnowledgeGraphResponse>(`${environment.apiBaseUrl}/projects/${projectId}/knowledge/graph`)
      .pipe(tap((graph) => this.graph.set(graph)));
  }

  ingestRepository(projectId: string, path: string): Observable<IngestRepositoryResponse> {
    return this.http
      .post<IngestRepositoryResponse>(
        `${environment.apiBaseUrl}/projects/${projectId}/knowledge/ingest-repository`,
        { path }
      )
      .pipe(tap(() => this.fetchCodeGraph(projectId).subscribe()));
  }

  fetchCodeGraph(projectId: string): Observable<CodeGraphResponse> {
    return this.http
      .get<CodeGraphResponse>(`${environment.apiBaseUrl}/projects/${projectId}/knowledge/code-graph`)
      .pipe(tap((graph) => this.codeGraph.set(graph)));
  }
}
