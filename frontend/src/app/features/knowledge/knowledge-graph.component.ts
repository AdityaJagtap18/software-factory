import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';
import { GraphEntity } from '../../core/models';

@Component({
  selector: 'sf-knowledge-graph',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './knowledge-graph.component.html',
  styleUrl: './knowledge-graph.component.scss'
})
export class KnowledgeGraphComponent {
  private readonly data = inject(MockDataService);

  readonly entities = this.data.graphEntities;
  readonly relationships = this.data.graphRelationships;
  readonly centerId = 'payment-service';

  readonly nodeTypes = [
    { label: 'Code', count: 8420, checked: true },
    { label: 'Repository', count: 6, checked: true },
    { label: 'Requirement', count: 214, checked: true },
    { label: 'Decision', count: 37, checked: true },
    { label: 'API', count: 432, checked: false },
    { label: 'Test', count: 1256, checked: false }
  ];

  selected = signal<GraphEntity | null>(null);
  resultsTab = signal<'related' | 'impact' | 'dependencies' | 'usage' | 'history'>('related');

  constructor() {
    this.selected.set(this.entities().find((e) => e.id === this.centerId) ?? null);
  }

  select(entity: GraphEntity) {
    this.selected.set(entity);
  }

  position(entity: GraphEntity) {
    if (entity.id === this.centerId) return { left: '50%', top: '50%' };
    const others = this.entities().filter((e) => e.id !== this.centerId);
    const idx = others.findIndex((e) => e.id === entity.id);
    const angle = (idx / others.length) * 2 * Math.PI - Math.PI / 2;
    const radius = 38;
    const left = 50 + radius * Math.cos(angle);
    const top = 50 + radius * Math.sin(angle) * 0.82;
    return { left: `${left}%`, top: `${top}%` };
  }

  private numericPosition(id: string) {
    const entity = this.entities().find((e) => e.id === id)!;
    const pos = this.position(entity);
    return { x: parseFloat(pos.left), y: parseFloat(pos.top) };
  }

  readonly edgeLines = () =>
    this.relationships().map((rel) => {
      const from = this.numericPosition(rel.from);
      const to = this.numericPosition(rel.to);
      return { ...from, x2: to.x, y2: to.y, label: rel.label };
    });
}
