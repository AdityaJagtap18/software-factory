import { Injectable, inject, signal } from '@angular/core';
import { environment } from '../../../environments/environment';
import { AuthService } from '../auth/auth.service';

export interface ProjectViewer {
  user_id: string;
  full_name: string;
}

/**
 * Real-time "who's viewing this project" presence, backed by an actual
 * WebSocket connection to the backend — the viewer list is whatever the
 * server just broadcast from its live connection registry, never a
 * client-side guess or a fabricated count.
 */
@Injectable({ providedIn: 'root' })
export class PresenceService {
  private readonly auth = inject(AuthService);

  readonly viewers = signal<ProjectViewer[]>([]);

  private socket: WebSocket | null = null;
  private currentProjectId: string | null = null;

  watch(projectId: string): void {
    if (this.currentProjectId === projectId && this.socket?.readyState === WebSocket.OPEN) {
      return;
    }
    this.stop();
    this.currentProjectId = projectId;

    const token = this.auth.accessToken;
    if (!token) return;

    const wsBase = environment.apiBaseUrl.replace(/^http/, 'ws');
    const socket = new WebSocket(`${wsBase}/projects/${projectId}/presence/ws?token=${encodeURIComponent(token)}`);
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        this.viewers.set(payload.viewers ?? []);
      } catch {
        // Malformed frame — ignore rather than guess at its content.
      }
    };
    socket.onclose = () => {
      if (this.socket === socket) {
        this.viewers.set([]);
      }
    };
    this.socket = socket;
  }

  stop(): void {
    this.socket?.close();
    this.socket = null;
    this.currentProjectId = null;
    this.viewers.set([]);
  }
}
