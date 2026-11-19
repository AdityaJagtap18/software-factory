import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiTask, CreateTaskPayload } from './task.models';

@Injectable({ providedIn: 'root' })
export class TaskService {
  private readonly http = inject(HttpClient);

  readonly tasks = signal<ApiTask[]>([]);
  readonly loaded = signal(false);

  listForProject(projectId: string): Observable<ApiTask[]> {
    return this.http.get<ApiTask[]>(`${environment.apiBaseUrl}/projects/${projectId}/tasks`).pipe(
      tap((tasks) => {
        this.tasks.set(tasks);
        this.loaded.set(true);
      })
    );
  }

  create(projectId: string, payload: CreateTaskPayload): Observable<ApiTask> {
    return this.http
      .post<ApiTask>(`${environment.apiBaseUrl}/projects/${projectId}/tasks`, payload)
      .pipe(tap((task) => this.tasks.update((list) => [task, ...list])));
  }

  start(projectId: string, taskId: string): Observable<ApiTask> {
    return this.http
      .post<ApiTask>(`${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/start`, {})
      .pipe(
        tap((task) => {
          this.tasks.update((list) => list.map((t) => (t.id === task.id ? task : t)));
        })
      );
  }
}
