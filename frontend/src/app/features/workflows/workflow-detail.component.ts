import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';
import { WorkflowDagNode } from '../../core/models';

type WfTab = 'workflow' | 'execution' | 'tasks' | 'runs' | 'artifacts' | 'logs';

@Component({
  selector: 'sf-workflow-detail',
  standalone: true,
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './workflow-detail.component.html',
  styleUrl: './workflow-detail.component.scss'
})
export class WorkflowDetailComponent {
  private readonly data = inject(MockDataService);

  readonly workflow = signal(this.data.workflows()[0]);
  tab = signal<WfTab>('workflow');
  readonly selectedNode = signal<WorkflowDagNode | null>(this.workflow().nodes.find((n) => n.status === 'active') ?? null);

  readonly liveLog = [
    '[16:22:01] INFO  Starting code generation for task TSK-9812',
    '[16:22:04] INFO  Loading project context from Neo4j (snapshot: s-1043)',
    '[16:22:09] INFO  Retrieved 24 relevant code references',
    '[16:22:15] INFO  Generating implementation (module: invoice_extractor)',
    '[16:24:31] INFO  Writing files to workspace...',
    '[16:24:48] INFO  Validating generated code (lint, formatting, static checks)',
    '[16:25:53] INFO  Code generation in progress... (72%)'
  ];

  readonly artifacts = [
    { name: 'invoice_extractor.py', size: '24.3 KB' },
    { name: 'models.py', size: '8.1 KB' },
    { name: 'implementation_notes.md', size: '4.7 KB' }
  ];

  select(node: WorkflowDagNode) {
    this.selectedNode.set(node);
  }

  edgePath(fromId: string, toId: string): string {
    const nodes = this.workflow().nodes;
    const from = nodes.find((n) => n.id === fromId)!;
    const to = nodes.find((n) => n.id === toId)!;
    const x1 = from.x * 170 + 70;
    const y1 = from.y * 100 + 35;
    const x2 = to.x * 170;
    const y2 = to.y * 100 + 35;
    const midX = (x1 + x2) / 2;
    return `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
  }
}
