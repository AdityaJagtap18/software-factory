import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { RouterLink, ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';
import { ProjectService } from '../../core/org/project.service';
import { ApiProject } from '../../core/auth/auth.models';

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
  private readonly projectService = inject(ProjectService);

  private readonly projectId = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });

  readonly project = signal<ApiProject | null>(null);
  readonly loading = signal(true);
  readonly notFound = signal(false);

  /**
   * Tasks/workflows/agents aren't backend-owned yet (Phase 3 of the execution
   * spec), so these tabs keep showing illustrative mock data until that lands.
   */
  readonly tasks = this.data.tasks;
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

  constructor() {
    effect(() => {
      const id = this.projectId()?.get('projectId');
      if (!id) return;
      this.loading.set(true);
      this.notFound.set(false);
      this.projectService.get(id).subscribe({
        next: (project) => {
          this.project.set(project);
          this.loading.set(false);
        },
        error: () => {
          this.notFound.set(true);
          this.loading.set(false);
        }
      });
    });
  }

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'Completed' || status === 'Active' || status === 'Success') return 'green';
    if (status === 'In Progress') return 'blue';
    if (status === 'Pending Review') return 'amber';
    return 'gray';
  }
}
