import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

@Component({
  selector: 'sf-dashboard',
  standalone: true,
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss'
})
export class DashboardComponent {
  private readonly data = inject(MockDataService);

  readonly user = this.data.currentUser;
  readonly stats = this.data.dashboardStats;
  readonly projects = this.data.projects;
  readonly recentActivity = this.data.recentActivity;
  readonly runningWorkflows = this.data.runningWorkflows;
  readonly systemHealth = this.data.systemHealth;

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'Active') return 'green';
    if (status === 'In Progress') return 'blue';
    if (status === 'Paused') return 'amber';
    return 'gray';
  }
}
