import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import {
  DependenciesResponse,
  GraphResponse,
  HistoryDiffResponse,
  HistoryResponse,
  ImpactResponse,
  IndexRunDetailResponse,
  IndexTriggerResponse,
  NodeDetailResponse,
  NodeNeighborsResponse,
  OverviewResponse,
  RepoBranchListResponse,
  SearchResponse,
  SettingsResponse,
  SettingsUpdateRequest,
} from './repository-intelligence.models';

@Injectable({ providedIn: 'root' })
export class RepositoryIntelligenceService {
  private readonly http = inject(HttpClient);

  getBranches(projectId: string, repositoryId: string): Observable<RepoBranchListResponse> {
    return this.http.get<RepoBranchListResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/repositories/${repositoryId}/branches`
    );
  }

  getOverview(projectId: string, repositoryId: string, branch?: string): Observable<OverviewResponse> {
    let params = new HttpParams().set('repository_id', repositoryId);
    if (branch) params = params.set('branch', branch);
    return this.http.get<OverviewResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/overview`,
      { params }
    );
  }

  getGraph(
    projectId: string,
    repositoryId: string,
    branch?: string,
    nodeType?: string,
    limit = 150
  ): Observable<GraphResponse> {
    let params = new HttpParams()
      .set('repository_id', repositoryId)
      .set('limit', limit.toString());
    if (branch) params = params.set('branch', branch);
    if (nodeType && nodeType !== 'All') params = params.set('node_type', nodeType);
    return this.http.get<GraphResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/graph`,
      { params }
    );
  }

  getNodeDetails(
    projectId: string,
    repositoryId: string,
    nodeId: string,
    branch?: string
  ): Observable<NodeDetailResponse> {
    let params = new HttpParams().set('repository_id', repositoryId);
    if (branch) params = params.set('branch', branch);
    return this.http.get<NodeDetailResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/graph/nodes/${encodeURIComponent(nodeId)}`,
      { params }
    );
  }

  getNodeNeighbors(
    projectId: string,
    repositoryId: string,
    nodeId: string,
    branch?: string,
    depth = 1
  ): Observable<NodeNeighborsResponse> {
    let params = new HttpParams()
      .set('repository_id', repositoryId)
      .set('node_id', nodeId)
      .set('depth', depth.toString());
    if (branch) params = params.set('branch', branch);
    return this.http.get<NodeNeighborsResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/graph/neighbors`,
      { params }
    );
  }

  search(
    projectId: string,
    repositoryId: string,
    query: string,
    mode = 'all',
    branch?: string
  ): Observable<SearchResponse> {
    let params = new HttpParams()
      .set('repository_id', repositoryId)
      .set('q', query)
      .set('mode', mode);
    if (branch) params = params.set('branch', branch);
    return this.http.get<SearchResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/search`,
      { params }
    );
  }

  getDependencies(projectId: string, repositoryId: string, branch?: string): Observable<DependenciesResponse> {
    let params = new HttpParams().set('repository_id', repositoryId);
    if (branch) params = params.set('branch', branch);
    return this.http.get<DependenciesResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/dependencies`,
      { params }
    );
  }

  getImpactAnalysis(
    projectId: string,
    repositoryId: string,
    nodeId: string,
    branch?: string
  ): Observable<ImpactResponse> {
    let params = new HttpParams().set('repository_id', repositoryId);
    if (branch) params = params.set('branch', branch);
    return this.http.get<ImpactResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/impact/${encodeURIComponent(nodeId)}`,
      { params }
    );
  }

  getHistory(projectId: string, repositoryId: string): Observable<HistoryResponse> {
    const params = new HttpParams().set('repository_id', repositoryId);
    return this.http.get<HistoryResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/history`,
      { params }
    );
  }

  diffHistory(projectId: string, runA: string, runB: string): Observable<HistoryDiffResponse> {
    const params = new HttpParams().set('run_a', runA).set('run_b', runB);
    return this.http.get<HistoryDiffResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/history/diff`,
      { params }
    );
  }

  triggerIndex(
    projectId: string,
    repositoryId: string,
    branch?: string,
    force = false
  ): Observable<IndexTriggerResponse> {
    return this.http.post<IndexTriggerResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/index`,
      { repository_id: repositoryId, branch, force }
    );
  }

  getIndexRunDetail(projectId: string, runId: string): Observable<IndexRunDetailResponse> {
    return this.http.get<IndexRunDetailResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/index/${runId}`
    );
  }

  getSettings(projectId: string, repositoryId: string): Observable<SettingsResponse> {
    const params = new HttpParams().set('repository_id', repositoryId);
    return this.http.get<SettingsResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/settings`,
      { params }
    );
  }

  updateSettings(projectId: string, payload: SettingsUpdateRequest): Observable<SettingsResponse> {
    return this.http.put<SettingsResponse>(
      `${environment.apiBaseUrl}/projects/${projectId}/repository-intelligence/settings`,
      payload
    );
  }
}
