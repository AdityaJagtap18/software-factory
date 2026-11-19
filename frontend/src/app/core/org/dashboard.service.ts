import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { DashboardSummary } from './dashboard.models';

@Injectable({ providedIn: 'root' })
export class DashboardService {
  private readonly http = inject(HttpClient);

  readonly summary = signal<DashboardSummary | null>(null);

  fetchSummary() {
    return this.http
      .get<DashboardSummary>(`${environment.apiBaseUrl}/dashboard/summary`)
      .pipe(tap((summary) => this.summary.set(summary)));
  }
}
