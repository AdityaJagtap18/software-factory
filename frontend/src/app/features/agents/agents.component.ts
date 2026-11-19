import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

type AgentsTab = 'registry' | 'runs' | 'capabilities' | 'providers' | 'health';
type DetailTab = 'overview' | 'configuration' | 'runs' | 'logs';

@Component({
  selector: 'sf-agents',
  standalone: true,
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './agents.component.html',
  styleUrl: './agents.component.scss'
})
export class AgentsComponent {
  private readonly data = inject(MockDataService);
  readonly agents = this.data.agents;

  tab = signal<AgentsTab>('registry');
  detailTab = signal<DetailTab>('overview');
  search = signal('');
  selected = signal(this.agents()[0]);

  readonly filtered = computed(() => {
    const term = this.search().toLowerCase();
    return this.agents().filter((a) => !term || a.name.toLowerCase().includes(term));
  });

  select(agent: ReturnType<typeof this.agents>[number]) {
    this.selected.set(agent);
  }

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'Active') return 'green';
    if (status === 'Idle') return 'amber';
    return 'gray';
  }
}
