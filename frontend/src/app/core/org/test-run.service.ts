import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiTestRun } from './test-run.models';

@Injectable({ providedIn: 'root' })
export class TestRunService {
  private readonly http = inject(HttpClient);

  readonly runs = signal<ApiTestRun[]>([]);
  readonly loaded = signal(false);

  listForTask(projectId: string, taskId: string): Observable<ApiTestRun[]> {
    return this.http
      .get<ApiTestRun[]>(`${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/test-runs`)
      .pipe(
        tap((runs) => {
          this.runs.set(runs);
          this.loaded.set(true);
        })
      );
  }

  trigger(projectId: string, taskId: string): Observable<ApiTestRun> {
    return this.http
      .post<ApiTestRun>(`${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/test-runs`, {})
      .pipe(tap((run) => this.runs.update((list) => [run, ...list])));
  }
}
