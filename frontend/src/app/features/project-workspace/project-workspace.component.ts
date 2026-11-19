import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink, ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

type TabId = 'overview' | 'tasks' | 'workflows' | 'agents' | 'knowledge' | 'artifacts' | 'activity' | 'settings';

@Component({
  selector: 'sf-project-workspace',
  standalone: true,
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './project-workspace.component.html',
  styleUrl: './project-workspace.component.scss'
})
export class ProjectWorkspaceComponent {
  private readonly data = inject(MockDataService);
  private readonly route = inject(ActivatedRoute);

  private readonly projectId = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });

  readonly project = computed(() => {
    const id = this.projectId()?.get('projectId');
    return this.data.projects().find((p) => p.id === id) ?? this.data.projects()[0];
  });

  readonly tasks = computed(() => this.data.tasks().filter((t) => t.project === this.project().slug));
  readonly workflows = this.data.runningWorkflows;
  readonly agents = this.data.agents;
  readonly recentActivity = this.data.recentActivity;

  readonly tabs: { id: TabId; label: string; icon: string }[] = [
    { id: 'overview', label: 'Overview', icon: 'navigation/dashboard' },
    { id: 'tasks', label: 'Tasks', icon: 'navigation/tasks' },
    { id: 'workflows', label: 'Workflows', icon: 'navigation/workflows' },
    { id: 'agents', label: 'Agents', icon: 'navigation/agents' },
    { id: 'knowledge', label: 'Knowledge', icon: 'navigation/knowledge' },
    { id: 'artifacts', label: 'Artifacts', icon: 'navigation/artifacts' },
    { id: 'activity', label: 'Activity', icon: 'navigation/monitoring' },
    { id: 'settings', label: 'Settings', icon: 'navigation/settings' }
  ];

  activeTab = signal<TabId>('overview');

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'Completed' || status === 'Active' || status === 'Success') return 'green';
    if (status === 'In Progress') return 'blue';
    if (status === 'Pending Review') return 'amber';
    return 'gray';
  }
}
