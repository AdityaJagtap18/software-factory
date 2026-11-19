import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

type ApprovalsTab = 'all' | 'code' | 'workflow' | 'knowledge' | 'prompt' | 'model' | 'access';

@Component({
  selector: 'sf-approvals',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './approvals.component.html',
  styleUrl: './approvals.component.scss'
})
export class ApprovalsComponent {
  private readonly data = inject(MockDataService);
  readonly approvals = this.data.approvals;

  tab = signal<ApprovalsTab>('all');
  selected = signal(this.approvals()[0]);

  readonly recentDecisions = [
    { title: 'PR: Add invoice validation rules', status: 'Approved', timestamp: '16 Nov, 04:21 PM' },
    { title: 'Update RAG knowledge base (OCR)', status: 'Approved', timestamp: '16 Nov, 11:03 AM' },
    { title: 'Publish agent prompt v2.2', status: 'Rejected', timestamp: '15 Nov, 05:47 PM' },
    { title: 'PR: Fix test flakiness in CI', status: 'Approved', timestamp: '15 Nov, 02:10 PM' }
  ];

  select(a: ReturnType<typeof this.approvals>[number]) {
    this.selected.set(a);
  }

  priorityTone(priority: string): 'red' | 'amber' | 'gray' {
    if (priority === 'High') return 'red';
    if (priority === 'Medium') return 'amber';
    return 'gray';
  }
}
