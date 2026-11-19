import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

type Range = '24h' | '7d' | '30d';
type MonTab = 'overview' | 'executions' | 'agents' | 'workflows' | 'providers' | 'costs' | 'incidents' | 'health';

@Component({
  selector: 'sf-monitoring',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './monitoring.component.html',
  styleUrl: './monitoring.component.scss'
})
export class MonitoringComponent {
  private readonly data = inject(MockDataService);

  range = signal<Range>('24h');
  tab = signal<MonTab>('overview');
  autoRefresh = signal(true);

  readonly alerts = this.data.monitoringAlerts;
  readonly agentPerformance = this.data.agents;
  readonly providers = this.data.providers;

  readonly executionStatus = [
    { label: 'Completed', value: 117, pct: 92.1, tone: 'green' as const },
    { label: 'Running', value: 6, pct: 4.7, tone: 'blue' as const },
    { label: 'Failed', value: 3, pct: 2.4, tone: 'red' as const },
    { label: 'Cancelled', value: 1, pct: 0.8, tone: 'gray' as const }
  ];

  readonly platformHealth = this.data.systemHealth;

  readonly recentExecutions = this.data.tasks;

  severityTone(severity: string): 'red' | 'amber' | 'blue' {
    if (severity === 'High') return 'red';
    if (severity === 'Medium') return 'amber';
    return 'blue';
  }
}
