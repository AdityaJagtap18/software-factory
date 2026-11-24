import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiApproval, ApprovalDecisionPayload } from './approval.models';

@Injectable({ providedIn: 'root' })
export class ApprovalService {
  private readonly http = inject(HttpClient);

  readonly approvals = signal<ApiApproval[]>([]);
  readonly loaded = signal(false);

  listForProject(projectId: string, status?: string): Observable<ApiApproval[]> {
    return this.http
      .get<ApiApproval[]>(`${environment.apiBaseUrl}/projects/${projectId}/approvals`, {
        params: status ? { status } : {}
      })
      .pipe(
        tap((approvals) => {
          this.approvals.set(approvals);
          this.loaded.set(true);
        })
      );
  }

  decide(projectId: string, approvalId: string, payload: ApprovalDecisionPayload): Observable<ApiApproval> {
    return this.http
      .post<ApiApproval>(
        `${environment.apiBaseUrl}/projects/${projectId}/approvals/${approvalId}/decide`,
        payload
      )
      .pipe(
        tap((updated) => {
          this.approvals.update((list) => list.map((a) => (a.id === updated.id ? updated : a)));
        })
      );
  }
}
