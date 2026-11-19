import { ChangeDetectionStrategy, Component, OnInit, effect, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';
import { AuthService } from '../../core/auth/auth.service';
import { OrganizationService } from '../../core/org/organization.service';
import { ProjectService } from '../../core/org/project.service';

@Component({
  selector: 'sf-dashboard',
  standalone: true,
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss'
})
export class DashboardComponent implements OnInit {
  private readonly data = inject(MockDataService);
  private readonly auth = inject(AuthService);
  private readonly orgService = inject(OrganizationService);
  private readonly projectService = inject(ProjectService);

  readonly currentUser = this.auth.currentUser;
  readonly stats = this.data.dashboardStats;
  readonly projects = this.projectService.projects;
  readonly recentActivity = this.data.recentActivity;
  readonly runningWorkflows = this.data.runningWorkflows;
  readonly systemHealth = this.data.systemHealth;

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
  }

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'Active') return 'green';
    if (status === 'In Progress') return 'blue';
    if (status === 'Paused') return 'amber';
    return 'gray';
  }
}
