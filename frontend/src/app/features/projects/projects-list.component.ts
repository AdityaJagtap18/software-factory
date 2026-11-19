import { ChangeDetectionStrategy, Component, inject, signal, computed } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

@Component({
  selector: 'sf-projects-list',
  standalone: true,
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './projects-list.component.html',
  styleUrl: './projects-list.component.scss'
})
export class ProjectsListComponent {
  private readonly data = inject(MockDataService);
  readonly allProjects = this.data.projects;

  search = signal('');
  statusFilter = signal<'All' | 'Active' | 'In Progress' | 'Paused' | 'Archived'>('All');

  readonly projects = computed(() => {
    const term = this.search().toLowerCase();
    return this.allProjects().filter((p) => {
      const matchesTerm = !term || p.name.toLowerCase().includes(term) || p.description.toLowerCase().includes(term);
      const matchesStatus = this.statusFilter() === 'All' || p.status === this.statusFilter();
      return matchesTerm && matchesStatus;
    });
  });

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'Active') return 'green';
    if (status === 'In Progress') return 'blue';
    if (status === 'Paused') return 'amber';
    return 'gray';
  }
}
