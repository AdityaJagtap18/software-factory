import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

@Component({
  selector: 'sf-prompts',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './prompts.component.html',
  styleUrl: './prompts.component.scss'
})
export class PromptsComponent {
  private readonly data = inject(MockDataService);
  readonly prompts = this.data.prompts;

  search = signal('');
  selected = signal(this.prompts()[0]);

  readonly filtered = computed(() => {
    const term = this.search().toLowerCase();
    return this.prompts().filter((p) => !term || p.name.toLowerCase().includes(term));
  });

  readonly versionHistory = [
    { version: 'v2.3', status: 'Published', date: '16 Nov 2026, 11:24 AM' },
    { version: 'v2.2', status: 'In Review', date: '14 Nov 2026, 09:10 AM' },
    { version: 'v2.1', status: 'Published', date: '10 Nov 2026, 05:32 PM' },
    { version: 'v2.0', status: 'Published', date: '05 Nov 2026, 03:17 PM' }
  ];

  readonly evalBreakdown = [
    { label: 'Correctness', value: 0.93 },
    { label: 'Instruction Following', value: 0.92 },
    { label: 'Code Quality', value: 0.9 },
    { label: 'Test Coverage', value: 0.89 },
    { label: 'Safety & Guardrails', value: 0.9 }
  ];

  select(prompt: ReturnType<typeof this.prompts>[number]) {
    this.selected.set(prompt);
  }

  statusTone(status: string): 'green' | 'amber' | 'gray' {
    if (status === 'Published') return 'green';
    if (status === 'In Review') return 'amber';
    return 'gray';
  }
}
