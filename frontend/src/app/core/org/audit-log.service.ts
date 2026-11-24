import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiAuditLog } from './audit-log.models';

@Injectable({ providedIn: 'root' })
export class AuditLogService {
  private readonly http = inject(HttpClient);

  readonly entries = signal<ApiAuditLog[]>([]);
  readonly loaded = signal(false);

  listForOrg(organizationId: string, filters: { action?: string; target_type?: string } = {}): Observable<ApiAuditLog[]> {
    const params: Record<string, string> = {};
    if (filters.action) params['action'] = filters.action;
    if (filters.target_type) params['target_type'] = filters.target_type;
    return this.http
      .get<ApiAuditLog[]>(`${environment.apiBaseUrl}/organizations/${organizationId}/audit-logs`, { params })
      .pipe(
        tap((entries) => {
          this.entries.set(entries);
          this.loaded.set(true);
        })
      );
  }
}
