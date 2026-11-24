import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { IconComponent } from '../../shared/icon/icon.component';
import { KnowledgeService } from '../../core/org/knowledge.service';
import { ProjectService } from '../../core/org/project.service';
import { OrganizationService } from '../../core/org/organization.service';
import { GitIntegrationService } from '../../core/org/git-integration.service';
import { KnowledgeNode, KnowledgeEdge } from '../../core/org/knowledge.models';

export type GraphViewMode = 'all' | 'project' | 'repository';

@Component({
  selector: 'sf-knowledge-graph',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './knowledge-graph.component.html',
  styleUrl: './knowledge-graph.component.scss'
})
export class KnowledgeGraphComponent {
  private readonly knowledgeService = inject(KnowledgeService);
  private readonly projectService = inject(ProjectService);
  private readonly orgService = inject(OrganizationService);
  private readonly gitService = inject(GitIntegrationService);

  readonly projects = this.projectService.projects;
  readonly projectsLoaded = this.projectService.loaded;
  readonly graph = this.knowledgeService.graph;
  readonly repoConnections = this.gitService.repositoryConnections;

  readonly selectedProjectId = signal<string>('');
  readonly viewMode = signal<GraphViewMode>('all');
  readonly searchQuery = signal<string>('');
  readonly selectedNodeId = signal<string | null>(null);

  readonly syncing = signal<boolean>(false);
  readonly syncMessage = signal<string>('');
  readonly syncError = signal<string>('');

  // Selected node types filter (type name -> boolean)
  readonly activeNodeTypes = signal<Record<string, boolean>>({});
  // Selected edge types filter (type name -> boolean)
  readonly activeEdgeTypes = signal<Record<string, boolean>>({});

  constructor() {
    this.orgService.listMine().subscribe({
      next: (orgs) => {
        if (orgs.length > 0) {
          const orgId = this.orgService.activeOrgId() || orgs[0].id;
          this.projectService.listForOrg(orgId).subscribe({
            next: (projects) => {
              if (projects.length > 0 && !this.selectedProjectId()) {
                this.selectProject(projects[0].id);
              }
            }
          });
        }
      }
    });

    // When graph updates, initialize node types and edge types filters
    effect(() => {
      const g = this.graph();
      if (!g || !g.nodes) return;
      const currentTypes = { ...this.activeNodeTypes() };
      let changed = false;
      for (const n of g.nodes) {
        if (currentTypes[n.type] === undefined) {
          currentTypes[n.type] = true;
          changed = true;
        }
      }
      if (changed) {
        this.activeNodeTypes.set(currentTypes);
      }

      const currentEdges = { ...this.activeEdgeTypes() };
      let edgeChanged = false;
      for (const e of g.edges) {
        if (currentEdges[e.type] === undefined) {
          currentEdges[e.type] = true;
          edgeChanged = true;
        }
      }
      if (edgeChanged) {
        this.activeEdgeTypes.set(currentEdges);
      }

      // If no node selected, select the project or first node
      if (!this.selectedNodeId() && g.nodes.length > 0) {
        const root = g.nodes.find((n) => n.type === 'Project' || n.type === 'Repository') || g.nodes[0];
        this.selectedNodeId.set(root.id);
      }
    });
  }

  selectProject(projectId: string): void {
    this.selectedProjectId.set(projectId);
    this.selectedNodeId.set(null);
    this.syncMessage.set('');
    this.syncError.set('');
    this.loadGraph();
  }

  setViewMode(mode: GraphViewMode): void {
    this.viewMode.set(mode);
    this.loadGraph();
  }

  loadGraph(): void {
    const pId = this.selectedProjectId();
    if (!pId) return;
    this.knowledgeService.fetchGraph(pId, this.viewMode()).subscribe();
    this.gitService.listRepositoryConnections(pId).subscribe();
  }

  syncAndBuildGraph(): void {
    const pId = this.selectedProjectId();
    if (!pId || this.syncing()) return;
    this.syncing.set(true);
    this.syncMessage.set('Syncing project entities into graph...');
    this.syncError.set('');

    this.knowledgeService.sync(pId).subscribe({
      next: (syncRes) => {
        if (!syncRes.connected) {
          this.syncing.set(false);
          this.syncError.set(`Neo4j sync failed: ${syncRes.detail}`);
          return;
        }
        this.syncMessage.set('Indexing repository code structure...');
        this.knowledgeService.ingestRepository(pId).subscribe({
          next: (ingestRes) => {
            this.syncing.set(false);
            if (ingestRes.connected) {
              this.syncMessage.set(
                `Synced ${syncRes.nodes_synced} project nodes and ${ingestRes.files_scanned} files (${ingestRes.symbols_found} symbols).`
              );
            } else {
              this.syncMessage.set(`Project synced (${syncRes.nodes_synced} nodes). Code note: ${ingestRes.detail}`);
            }
            this.loadGraph();
          },
          error: (err) => {
            this.syncing.set(false);
            this.syncMessage.set(`Project synced (${syncRes.nodes_synced} nodes). Code indexing unavailable.`);
            this.loadGraph();
          }
        });
      },
      error: (err) => {
        this.syncing.set(false);
        this.syncError.set(err?.error?.detail ?? 'Failed to sync knowledge graph.');
      }
    });
  }

  readonly availableNodeTypes = computed(() => {
    const g = this.graph();
    if (!g || !g.nodes) return [];
    const counts: Record<string, number> = {};
    for (const n of g.nodes) {
      counts[n.type] = (counts[n.type] || 0) + 1;
    }
    const filterState = this.activeNodeTypes();
    return Object.entries(counts).map(([type, count]) => ({
      type,
      count,
      checked: filterState[type] !== false
    }));
  });

  readonly availableEdgeTypes = computed(() => {
    const g = this.graph();
    if (!g || !g.edges) return [];
    const counts: Record<string, number> = {};
    for (const e of g.edges) {
      counts[e.type] = (counts[e.type] || 0) + 1;
    }
    const filterState = this.activeEdgeTypes();
    return Object.entries(counts).map(([type, count]) => ({
      type,
      count,
      checked: filterState[type] !== false
    }));
  });

  toggleNodeType(type: string): void {
    const current = { ...this.activeNodeTypes() };
    current[type] = !current[type];
    this.activeNodeTypes.set(current);
  }

  toggleEdgeType(type: string): void {
    const current = { ...this.activeEdgeTypes() };
    current[type] = !current[type];
    this.activeEdgeTypes.set(current);
  }

  readonly filteredNodes = computed<KnowledgeNode[]>(() => {
    const g = this.graph();
    if (!g || !g.nodes) return [];
    const nodeTypeFilter = this.activeNodeTypes();
    const query = this.searchQuery().trim().toLowerCase();

    return g.nodes.filter((node) => {
      if (nodeTypeFilter[node.type] === false) return false;
      if (query) {
        const matchesLabel = node.label.toLowerCase().includes(query);
        const matchesType = node.type.toLowerCase().includes(query);
        const matchesPath = String(node.properties['path'] || '').toLowerCase().includes(query);
        if (!matchesLabel && !matchesType && !matchesPath) return false;
      }
      return true;
    });
  });

  readonly filteredEdges = computed<KnowledgeEdge[]>(() => {
    const g = this.graph();
    if (!g || !g.edges) return [];
    const edgeTypeFilter = this.activeEdgeTypes();
    const validNodeIds = new Set(this.filteredNodes().map((n) => n.id));

    return g.edges.filter((edge) => {
      if (edgeTypeFilter[edge.type] === false) return false;
      return validNodeIds.has(edge.source) && validNodeIds.has(edge.target);
    });
  });

  readonly selectedNode = computed<KnowledgeNode | null>(() => {
    const id = this.selectedNodeId();
    if (!id) return null;
    const g = this.graph();
    return g?.nodes.find((n) => n.id === id) ?? null;
  });

  selectNode(node: KnowledgeNode): void {
    this.selectedNodeId.set(node.id);
  }

  nodeTone(type: string): string {
    switch (type.toLowerCase()) {
      case 'project': return 'violet';
      case 'repository': return 'amber';
      case 'file': return 'blue';
      case 'class': return 'green';
      case 'function': return 'green';
      case 'module': return 'violet';
      case 'task': return 'blue';
      case 'workflow': return 'amber';
      case 'user': return 'gray';
      default: return 'blue';
    }
  }

  nodeIcon(type: string): string {
    switch (type.toLowerCase()) {
      case 'project': return 'navigation/dashboard';
      case 'repository': return 'navigation/repositories';
      case 'file': return 'workspace/code-diff';
      case 'class': return 'agents/coding-agent';
      case 'function': return 'workspace/code-search';
      case 'module': return 'navigation/artifacts';
      case 'task': return 'navigation/tasks';
      case 'workflow': return 'navigation/workflows';
      case 'user': return 'navigation/agents';
      default: return 'navigation/knowledge';
    }
  }

  // Positioning nodes on the 100x100 virtual canvas
  nodePosition(node: KnowledgeNode, index: number, total: number) {
    const selected = this.selectedNode();
    const isRoot = node.id === selected?.id || node.type === 'Project' || node.type === 'Repository';

    if (total === 1) return { left: '50%', top: '50%' };
    if (isRoot && node.id === selected?.id) return { left: '50%', top: '50%' };

    const angle = (index / total) * 2 * Math.PI - Math.PI / 2;
    const radiusX = 38;
    const radiusY = 36;
    const left = 50 + radiusX * Math.cos(angle);
    const top = 50 + radiusY * Math.sin(angle);
    return { left: `${Math.max(8, Math.min(92, left))}%`, top: `${Math.max(8, Math.min(92, top))}%` };
  }

  readonly edgeLines = computed(() => {
    const nodes = this.filteredNodes();
    const nodeMap = new Map<string, { x: number; y: number }>();
    const total = nodes.length;

    nodes.forEach((n, idx) => {
      const pos = this.nodePosition(n, idx, total);
      nodeMap.set(n.id, { x: parseFloat(pos.left), y: parseFloat(pos.top) });
    });

    const lines: Array<{ x1: number; y1: number; x2: number; y2: number; label: string }> = [];
    for (const edge of this.filteredEdges()) {
      const from = nodeMap.get(edge.source);
      const to = nodeMap.get(edge.target);
      if (from && to) {
        lines.push({ x1: from.x, y1: from.y, x2: to.x, y2: to.y, label: edge.type });
      }
    }
    return lines;
  });

  // Statistics computed from actual data
  readonly totalEntities = computed(() => this.graph()?.nodes?.length || 0);
  readonly totalRelationships = computed(() => this.graph()?.edges?.length || 0);
  readonly repoCount = computed(() => this.graph()?.nodes?.filter((n) => n.type === 'Repository').length || 0);
  readonly fileCount = computed(() => this.graph()?.nodes?.filter((n) => n.type === 'File').length || 0);
  readonly taskCount = computed(() => this.graph()?.nodes?.filter((n) => n.type === 'Task').length || 0);
  readonly symbolCount = computed(() => this.graph()?.nodes?.filter((n) => n.type === 'Class' || n.type === 'Function').length || 0);

  // Relationships involving the selected node
  readonly selectedNodeRelationships = computed(() => {
    const node = this.selectedNode();
    if (!node) return [];
    const g = this.graph();
    if (!g) return [];
    const nodeMap = new Map<string, KnowledgeNode>();
    g.nodes.forEach((n) => nodeMap.set(n.id, n));

    const rels: Array<{ direction: 'out' | 'in'; type: string; otherLabel: string; otherType: string }> = [];
    for (const edge of g.edges) {
      if (edge.source === node.id) {
        const target = nodeMap.get(edge.target);
        rels.push({
          direction: 'out',
          type: edge.type,
          otherLabel: target?.label || edge.target,
          otherType: target?.type || 'Entity'
        });
      } else if (edge.target === node.id) {
        const source = nodeMap.get(edge.source);
        rels.push({
          direction: 'in',
          type: edge.type,
          otherLabel: source?.label || edge.source,
          otherType: source?.type || 'Entity'
        });
      }
    }
    return rels;
  });

  objectKeys(obj: Record<string, unknown> | undefined): string[] {
    return obj ? Object.keys(obj) : [];
  }
}
