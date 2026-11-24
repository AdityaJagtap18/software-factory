import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ApiNotification } from './notification.models';

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private readonly http = inject(HttpClient);

  readonly notifications = signal<ApiNotification[]>([]);
  readonly unreadCount = signal(0);

  refreshUnreadCount(): void {
    this.http
      .get<{ count: number }>(`${environment.apiBaseUrl}/notifications/unread-count`)
      .subscribe({ next: (res) => this.unreadCount.set(res.count) });
  }

  list(): Observable<ApiNotification[]> {
    return this.http.get<ApiNotification[]>(`${environment.apiBaseUrl}/notifications`).pipe(
      tap((notifications) => this.notifications.set(notifications))
    );
  }

  markRead(id: string): Observable<ApiNotification> {
    return this.http.post<ApiNotification>(`${environment.apiBaseUrl}/notifications/${id}/read`, {}).pipe(
      tap((updated) => {
        this.notifications.update((list) => list.map((n) => (n.id === updated.id ? updated : n)));
        this.unreadCount.update((c) => Math.max(0, c - 1));
      })
    );
  }
}
