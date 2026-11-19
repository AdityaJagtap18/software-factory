import { ChangeDetectionStrategy, Component, OnInit, computed, effect, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { AuthService } from '../../core/auth/auth.service';
import { OrganizationService } from '../../core/org/organization.service';
import { ProjectService } from '../../core/org/project.service';
import { DashboardService } from '../../core/org/dashboard.service';

@Component({
  selector: 'sf-dashboard',
  standalone: true,
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss'
})
export class DashboardComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly orgService = inject(OrganizationService);
  private readonly projectService = inject(ProjectService);
  private readonly dashboardService = inject(DashboardService);

  readonly currentUser = this.auth.currentUser;
  readonly projects = this.projectService.projects;
  readonly summary = this.dashboardService.summary;

  readonly stats = computed(() => {
    const s = this.summary();
    if (!s) return [];
    return [
      { label: 'Projects', value: s.projects, icon: 'navigation/projects' },
      { label: 'Tasks (running / total)', value: `${s.tasks_running} / ${s.tasks_total}`, icon: 'navigation/tasks' },
      { label: 'Workflows (running / total)', value: `${s.workflows_running} / ${s.workflows_total}`, icon: 'navigation/workflows' },
      { label: 'Connections configured', value: s.connections_configured, icon: 'navigation/providers' }
    ];
  });

  readonly recentActivity = computed(() => this.summary()?.recent_activity ?? []);
  readonly runningWorkflows = computed(() => this.summary()?.running_workflows ?? []);
  readonly systemHealth = computed(() => this.summary()?.system_health ?? []);
  readonly allHealthy = computed(() => this.systemHealth().every((h) => h.connected));

  constructor() {
    effect(() => {
      const orgId = this.orgService.activeOrgId();
      if (orgId) {
        this.projectService.listForOrg(orgId).subscribe();
      }
    });
  }

  ngOnInit(): void {
    if (!this.currentUser()) {
      this.auth.fetchCurrentUser().subscribe();
    }
    this.dashboardService.fetchSummary().subscribe();
  }

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'Active') return 'green';
    if (status === 'In Progress') return 'blue';
    if (status === 'Paused') return 'amber';
    return 'gray';
  }

  elapsedLabel(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  }

  relativeTime(isoTimestamp: string): string {
    const diffMs = Date.now() - new Date(isoTimestamp).getTime();
    const seconds = Math.max(0, Math.round(diffMs / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  }
}
