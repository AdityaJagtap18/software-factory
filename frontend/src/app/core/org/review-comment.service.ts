import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiReviewComment, ReviewCommentCreatePayload } from './review-comment.models';

@Injectable({ providedIn: 'root' })
export class ReviewCommentService {
  private readonly http = inject(HttpClient);

  readonly comments = signal<ApiReviewComment[]>([]);
  readonly loaded = signal(false);

  listForTask(projectId: string, taskId: string): Observable<ApiReviewComment[]> {
    return this.http
      .get<ApiReviewComment[]>(
        `${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/review-comments`
      )
      .pipe(
        tap((comments) => {
          this.comments.set(comments);
          this.loaded.set(true);
        })
      );
  }

  create(projectId: string, taskId: string, payload: ReviewCommentCreatePayload): Observable<ApiReviewComment> {
    return this.http
      .post<ApiReviewComment>(
        `${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/review-comments`,
        payload
      )
      .pipe(tap((comment) => this.comments.update((list) => [...list, comment])));
  }

  resolve(projectId: string, taskId: string, commentId: string): Observable<ApiReviewComment> {
    return this.http
      .post<ApiReviewComment>(
        `${environment.apiBaseUrl}/projects/${projectId}/tasks/${taskId}/review-comments/${commentId}/resolve`,
        {}
      )
      .pipe(
        tap((updated) => {
          this.comments.update((list) => list.map((c) => (c.id === updated.id ? updated : c)));
        })
      );
  }

  reset(): void {
    this.comments.set([]);
    this.loaded.set(false);
  }
}
