import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { NgTemplateOutlet } from '@angular/common';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';
import { RepoTreeNode } from '../../core/models';

type RiTab = 'overview' | 'graph' | 'search' | 'dependencies' | 'impact' | 'history' | 'indexing' | 'settings';

@Component({
  selector: 'sf-repository-intelligence',
  standalone: true,
  imports: [RouterLink, IconComponent, NgTemplateOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './repository-intelligence.component.html',
  styleUrl: './repository-intelligence.component.scss'
})
export class RepositoryIntelligenceComponent {
  private readonly data = inject(MockDataService);

  readonly repoTree = this.data.repoTree;
  tab = signal<RiTab>('graph');

  readonly dependencies = [
    { name: 'DocumentParserService', type: 'Service', direction: 'Out (Calls)' },
    { name: 'ClassificationService', type: 'Service', direction: 'Out (Calls)' },
    { name: 'InvoiceRepository', type: 'Repository', direction: 'Out (Persists)' },
    { name: 'OCRClient', type: 'Client', direction: 'Out (Integrates)' }
  ];

  readonly impact = [
    { icon: 'workspace/code-diff', value: 3, label: 'Direct Consumers' },
    { icon: 'navigation/artifacts', value: 12, label: 'Transitive Consumers' },
    { icon: 'agents/testing-agent', value: 5, label: 'Test Classes' },
    { icon: 'navigation/workflows', value: 2, label: 'Workflows' }
  ];

  expandedNodes = signal(new Set<string>(['fintrix-platform', 'src/main/java/com/fintrix', 'service', 'controller']));

  toggle(node: RepoTreeNode) {
    const next = new Set(this.expandedNodes());
    if (next.has(node.name)) next.delete(node.name);
    else next.add(node.name);
    this.expandedNodes.set(next);
  }

  isExpanded(node: RepoTreeNode) {
    return this.expandedNodes().has(node.name);
  }
}
