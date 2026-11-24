import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  ViewChild,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { OrganizationService } from '../../core/org/organization.service';
import { ProjectService } from '../../core/org/project.service';
import { GitIntegrationService } from '../../core/org/git-integration.service';
import { RepositoryIntelligenceService } from '../../core/org/repository-intelligence.service';
import {
  BranchInfo,
  CommunityPayload,
  DependenciesResponse,
  GraphEdgePayload,
  GraphNodePayload,
  GraphResponse,
  HistoryDiffResponse,
  HistoryResponse,
  ImpactResponse,
  IndexRunDetailResponse,
  NodeDetailResponse,
  OverviewResponse,
  SearchResultItem,
  SettingsResponse,
} from '../../core/org/repository-intelligence.models';

export type RiTab =
  | 'overview'
  | 'graph'
  | 'search'
  | 'dependencies'
  | 'impact'
  | 'history'
  | 'indexing'
  | 'settings';

export type LayoutMode = 'force' | 'radial' | 'hierarchical';

interface SimNode extends GraphNodePayload {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
}

interface SimEdge {
  source: SimNode;
  target: SimNode;
  type: string;
  provenance: string;
  weight: number;
}

@Component({
  selector: 'sf-repository-intelligence',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './repository-intelligence.component.html',
  styleUrl: './repository-intelligence.component.scss',
})
export class RepositoryIntelligenceComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('graphCanvas') canvasRef?: ElementRef<HTMLCanvasElement>;

  private readonly route = inject(ActivatedRoute);
  private readonly orgService = inject(OrganizationService);
  private readonly projectService = inject(ProjectService);
  private readonly gitService = inject(GitIntegrationService);
  private readonly riService = inject(RepositoryIntelligenceService);

  readonly tab = signal<RiTab>('graph');

  // Selectors State
  readonly projects = this.projectService.projects;
  readonly repoConnections = this.gitService.repositoryConnections;
  readonly branches = signal<BranchInfo[]>([]);

  readonly selectedProjectId = signal<string>('');
  readonly selectedRepoId = signal<string>('');
  readonly selectedBranch = signal<string>('master');

  // Loading States
  readonly loading = signal<boolean>(false);
  readonly indexing = signal<boolean>(false);
  readonly errorMessage = signal<string>('');
  readonly successMessage = signal<string>('');

  // 1. Overview State
  readonly overviewData = signal<OverviewResponse | null>(null);

  // 2. Graph State
  readonly graphData = signal<GraphResponse | null>(null);
  readonly communities = signal<CommunityPayload[]>([]);
  readonly communityVisibility = signal<Record<string, boolean>>({});
  readonly selectAllCommunities = signal<boolean>(true);
  readonly hoveredCommunityId = signal<string | null>(null);

  readonly selectedGraphNodeType = signal<string>('All');
  readonly graphLimit = signal<number>(400);
  readonly selectedNodeId = signal<string | null>(null);
  readonly hoveredNodeId = signal<string | null>(null);
  readonly selectedNodeDetail = signal<NodeDetailResponse | null>(null);
  readonly nodeDetailLoading = signal<boolean>(false);
  readonly showSourcePreview = signal<boolean>(false);

  readonly layoutMode = signal<LayoutMode>('force');
  readonly graphSearchQuery = signal<string>('');

  // Canvas Pan/Zoom
  private scale = 1.0;
  private panX = 0;
  private panY = 0;
  private isPanning = false;
  private panStartX = 0;
  private panStartY = 0;
  private draggedNode: SimNode | null = null;
  private animFrameId: number | null = null;
  private simAlpha = 1.0;

  // Simulation Data
  private simNodes: SimNode[] = [];
  private simEdges: SimEdge[] = [];
  private nodeMap = new Map<string, SimNode>();
  private neighborSet = new Set<string>();

  // 3. Search State
  readonly searchQuery = signal<string>('');
  readonly searchMode = signal<'all' | 'file' | 'symbol' | 'code' | 'intent'>('all');
  readonly searchResults = signal<SearchResultItem[]>([]);
  readonly searching = signal<boolean>(false);

  // 4. Dependencies State
  readonly dependenciesData = signal<DependenciesResponse | null>(null);
  readonly depSubTab = signal<'external' | 'internal'>('external');

  // 5. Impact Analysis State
  readonly impactTargetId = signal<string>('');
  readonly impactData = signal<ImpactResponse | null>(null);
  readonly impactLoading = signal<boolean>(false);

  // 6. History State
  readonly historyData = signal<HistoryResponse | null>(null);
  readonly selectedRunA = signal<string>('');
  readonly selectedRunB = signal<string>('');
  readonly diffData = signal<HistoryDiffResponse | null>(null);
  readonly diffLoading = signal<boolean>(false);

  // 7. Indexing State
  readonly indexForce = signal<boolean>(false);
  readonly liveRunDetail = signal<IndexRunDetailResponse | null>(null);

  // 8. Settings State
  readonly settingsData = signal<SettingsResponse | null>(null);
  readonly settingsSaving = signal<boolean>(false);
  settingsDefaultBranch = 'master';
  settingsIncludedPaths = '';
  settingsExcludedPaths = 'node_modules, dist, .git, __pycache__, venv, .venv, build';
  settingsMaxFileSizeKb = 500;
  settingsAutoIndex = true;

  // Computed Properties
  readonly currentProject = computed(() =>
    this.projects().find((p) => p.id === this.selectedProjectId())
  );

  readonly currentRepo = computed(() =>
    this.repoConnections().find((r) => r.id === this.selectedRepoId())
  );

  readonly statusBadge = computed(() => {
    if (this.indexing()) return { label: 'Indexing...', color: 'blue' };
    const ov = this.overviewData();
    if (!ov) return { label: 'Checking', color: 'gray' };
    const st = ov.index_status.status;
    if (st === 'COMPLETED') return { label: 'Indexed', color: 'green' };
    if (st === 'RUNNING') return { label: 'Indexing...', color: 'blue' };
    if (st === 'FAILED') return { label: 'Index Failed', color: 'red' };
    return { label: 'Not Indexed', color: 'amber' };
  });

  readonly filteredGraphSearchNodes = computed(() => {
    const q = this.graphSearchQuery().trim().toLowerCase();
    const gd = this.graphData();
    if (!q || !gd) return [];
    return gd.nodes
      .filter(
        (n) =>
          n.label.toLowerCase().includes(q) ||
          (n.file_path && n.file_path.toLowerCase().includes(q))
      )
      .slice(0, 15);
  });

  ngOnInit(): void {
    const routeProjId = this.route.snapshot.paramMap.get('projectId');
    this.orgService.listMine().subscribe({
      next: (orgs) => {
        if (orgs.length > 0) {
          const orgId = this.orgService.activeOrgId() || orgs[0].id;
          this.projectService.listForOrg(orgId).subscribe({
            next: (projs) => {
              if (projs.length > 0) {
                const targetProj = routeProjId
                  ? projs.find((p) => p.id === routeProjId) || projs[0]
                  : projs[0];
                this.selectProject(targetProj.id);
              }
            },
          });
        }
      },
    });
  }

  ngAfterViewInit(): void {
    if (this.tab() === 'graph') {
      setTimeout(() => this.initCanvasSimulation(5), 100);
    }
  }

  ngOnDestroy(): void {
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId);
    }
  }

  selectProject(projectId: string): void {
    this.selectedProjectId.set(projectId);
    this.gitService.listRepositoryConnections(projectId).subscribe({
      next: (repos) => {
        if (repos.length > 0) {
          this.selectRepository(repos[0].id);
        } else {
          this.selectedRepoId.set('');
          this.overviewData.set(null);
          this.graphData.set(null);
          this.communities.set([]);
        }
      },
    });
  }

  selectRepository(repoId: string): void {
    this.selectedRepoId.set(repoId);
    const pid = this.selectedProjectId();
    this.riService.getBranches(pid, repoId).subscribe({
      next: (res) => {
        this.branches.set(res.branches);
        const def = res.branches.find((b) => b.is_default)?.name || res.default_branch || 'master';
        this.selectedBranch.set(def);
        this.loadActiveTab();
      },
      error: () => {
        this.branches.set([{ name: 'master', is_default: true }]);
        this.selectedBranch.set('master');
        this.loadActiveTab();
      },
    });
  }

  onBranchChange(branch: string): void {
    this.selectedBranch.set(branch);
    this.loadActiveTab();
  }

  switchTab(t: RiTab): void {
    this.tab.set(t);
    this.errorMessage.set('');
    this.successMessage.set('');
    this.loadActiveTab();

    if (t === 'graph') {
      setTimeout(() => this.initCanvasSimulation(5), 100);
    } else if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
  }

  loadActiveTab(): void {
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    const branch = this.selectedBranch();
    if (!pid || !rid) return;

    // Keep header status badge synced
    this.riService.getOverview(pid, rid, branch).subscribe({
      next: (res) => this.overviewData.set(res),
      error: () => {},
    });

    const currentTab = this.tab();
    if (currentTab === 'overview') {
      this.loadOverview();
    } else if (currentTab === 'graph') {
      this.loadGraph();
    } else if (currentTab === 'dependencies') {
      this.loadDependencies();
    } else if (currentTab === 'history') {
      this.loadHistory();
    } else if (currentTab === 'indexing') {
      this.loadIndexing();
    } else if (currentTab === 'settings') {
      this.loadSettings();
    }
  }

  // 1. Overview
  loadOverview(): void {
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;
    this.loading.set(true);
    this.riService.getOverview(pid, rid, this.selectedBranch()).subscribe({
      next: (res) => {
        this.overviewData.set(res);
        this.loading.set(false);
      },
      error: () => {
        this.errorMessage.set('Could not load repository overview');
        this.loading.set(false);
      },
    });
  }

  // 2. Graph & Communities
  loadGraph(): void {
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;
    this.loading.set(true);
    this.riService
      .getGraph(
        pid,
        rid,
        this.selectedBranch(),
        this.selectedGraphNodeType(),
        this.graphLimit()
      )
      .subscribe({
        next: (res) => {
          this.graphData.set(res);
          this.communities.set(res.communities || []);

          const visMap: Record<string, boolean> = {};
          (res.communities || []).forEach((c) => (visMap[c.id] = true));
          this.communityVisibility.set(visMap);
          this.selectAllCommunities.set(true);

          this.loading.set(false);
          setTimeout(() => this.initCanvasSimulation(5), 30);

          if (res.nodes.length > 0 && !this.selectedNodeId()) {
            this.selectNode(res.nodes[0].id);
          }
        },
        error: () => {
          this.errorMessage.set('Failed to load repository graph');
          this.loading.set(false);
        },
      });
  }

  // Canvas Force-Directed Engine
  private initCanvasSimulation(retries = 5): void {
    const canvas = this.canvasRef?.nativeElement;
    const gd = this.graphData();
    if (!canvas) {
      if (retries > 0) {
        setTimeout(() => this.initCanvasSimulation(retries - 1), 60);
      }
      return;
    }
    if (!gd || !gd.nodes || gd.nodes.length === 0) return;

    const parent = canvas.parentElement;
    const width = Math.max(600, parent ? parent.clientWidth : 900);
    const height = Math.max(500, parent ? parent.clientHeight : 640);

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    const comms = gd.communities || [];
    const commCount = Math.max(1, comms.length);
    const commCenters = new Map<string, { x: number; y: number }>();
    const orbitR = Math.min(width, height) * 0.32;
    comms.forEach((c, idx) => {
      const angle = (2 * Math.PI * idx) / commCount;
      commCenters.set(c.id, {
        x: width / 2 + orbitR * Math.cos(angle),
        y: height / 2 + orbitR * Math.sin(angle),
      });
    });

    this.simNodes = gd.nodes.map((n, i) => {
      const cCenter = (n.community_id && commCenters.get(n.community_id)) || {
        x: width / 2,
        y: height / 2,
      };
      const jitterAngle = Math.random() * 2 * Math.PI;
      const jitterDist = Math.random() * 80;
      const rad = Math.max(4, Math.min(13, Math.sqrt((n.degree || 1) * 3.2)));
      return {
        ...n,
        x: cCenter.x + jitterDist * Math.cos(jitterAngle),
        y: cCenter.y + jitterDist * Math.sin(jitterAngle),
        vx: 0,
        vy: 0,
        radius: rad,
      };
    });

    this.nodeMap.clear();
    this.simNodes.forEach((n) => this.nodeMap.set(n.id, n));

    this.simEdges = [];
    for (const e of gd.edges) {
      const s = this.nodeMap.get(e.source);
      const t = this.nodeMap.get(e.target);
      if (s && t) {
        this.simEdges.push({
          source: s,
          target: t,
          type: e.type,
          provenance: e.provenance,
          weight: e.weight,
        });
      }
    }

    this.simAlpha = 1.0;
    this.scale = 1.0;
    this.panX = 0;
    this.panY = 0;

    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId);
    }
    this.runSimulationLoop(canvas, ctx, width, height, commCenters);
  }

  private runSimulationLoop(
    canvas: HTMLCanvasElement,
    ctx: CanvasRenderingContext2D,
    w: number,
    h: number,
    commCenters: Map<string, { x: number; y: number }>
  ): void {
    const loop = () => {
      this.tickPhysics(w, h, commCenters);
      this.drawCanvas(ctx, w, h);
      this.animFrameId = requestAnimationFrame(loop);
    };
    this.animFrameId = requestAnimationFrame(loop);
  }

  private tickPhysics(
    w: number,
    h: number,
    commCenters: Map<string, { x: number; y: number }>
  ): void {
    if (this.simAlpha < 0.005) return; // Stabilized
    const alpha = this.simAlpha;
    const mode = this.layoutMode();
    const vis = this.communityVisibility();

    if (mode === 'force') {
      // 1. Community Clustering Force
      for (const n of this.simNodes) {
        if (n.community_id && vis[n.community_id] !== false) {
          const center = commCenters.get(n.community_id);
          if (center) {
            n.vx += (center.x - n.x) * 0.04 * alpha;
            n.vy += (center.y - n.y) * 0.04 * alpha;
          }
        }
        // Center gravity
        n.vx += (w / 2 - n.x) * 0.008 * alpha;
        n.vy += (h / 2 - n.y) * 0.008 * alpha;
      }

      // 2. Link Spring Force
      for (const e of this.simEdges) {
        if (
          e.source.community_id &&
          vis[e.source.community_id] === false &&
          e.target.community_id &&
          vis[e.target.community_id] === false
        ) {
          continue;
        }
        const dx = e.target.x - e.source.x;
        const dy = e.target.y - e.source.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetDist = 45;
        const force = ((dist - targetDist) / dist) * 0.06 * alpha;
        e.source.vx += dx * force;
        e.source.vy += dy * force;
        e.target.vx -= dx * force;
        e.target.vy -= dy * force;
      }

      // 3. Many-body Repulsion
      const nodeCount = this.simNodes.length;
      for (let i = 0; i < nodeCount; i++) {
        const u = this.simNodes[i];
        if (u.community_id && vis[u.community_id] === false) continue;
        for (let j = i + 1; j < nodeCount; j++) {
          const v = this.simNodes[j];
          if (v.community_id && vis[v.community_id] === false) continue;
          const dx = v.x - u.x;
          const dy = v.y - u.y;
          const distSq = dx * dx + dy * dy + 1;
          if (distSq < 25000) {
            const dist = Math.sqrt(distSq);
            const repel = (320 / (distSq + 20)) * alpha;
            const rx = (dx / dist) * repel;
            const ry = (dy / dist) * repel;
            u.vx -= rx;
            u.vy -= ry;
            v.vx += rx;
            v.vy += ry;
          }
        }
      }
    } else if (mode === 'radial') {
      // Radial ring layout
      const center = { x: w / 2, y: h / 2 };
      for (const n of this.simNodes) {
        const ring = Math.min(3, Math.floor((n.degree || 1) / 3));
        const targetR = 80 + ring * 100;
        const dx = n.x - center.x;
        const dy = n.y - center.y;
        const currR = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = ((currR - targetR) / currR) * 0.05 * alpha;
        n.vx -= dx * force;
        n.vy -= dy * force;
      }
    } else if (mode === 'hierarchical') {
      // Layered top-down
      for (const e of this.simEdges) {
        const dy = e.target.y - e.source.y;
        if (dy < 60) {
          e.target.vy += (60 - dy) * 0.05 * alpha;
          e.source.vy -= (60 - dy) * 0.05 * alpha;
        }
      }
    }

    // Velocity update & damping
    for (const n of this.simNodes) {
      if (this.draggedNode === n) continue;
      n.vx *= 0.88;
      n.vy *= 0.88;
      n.x += n.vx;
      n.y += n.vy;
    }

    this.simAlpha *= 0.985;
  }

  private drawCanvas(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    ctx.save();
    ctx.clearRect(0, 0, w, h);

    // Deep Dark Surface background
    ctx.fillStyle = '#0a0e17';
    ctx.fillRect(0, 0, w, h);

    // Subtle Grid Points
    ctx.fillStyle = 'rgba(255, 255, 255, 0.03)';
    for (let x = 0; x < w; x += 28) {
      for (let y = 0; y < h; y += 28) {
        ctx.fillRect(x, y, 1.5, 1.5);
      }
    }

    // Apply Pan and Zoom
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.scale, this.scale);

    const selId = this.selectedNodeId();
    const hovId = this.hoveredNodeId();
    const hovCommId = this.hoveredCommunityId();
    const vis = this.communityVisibility();
    const activeTarget = selId || hovId;

    // 1. Draw Edges
    for (const e of this.simEdges) {
      const sVis = !e.source.community_id || vis[e.source.community_id] !== false;
      const tVis = !e.target.community_id || vis[e.target.community_id] !== false;
      if (!sVis || !tVis) continue;

      const isConnected =
        activeTarget &&
        (e.source.id === activeTarget || e.target.id === activeTarget);

      ctx.beginPath();
      ctx.moveTo(e.source.x, e.source.y);
      ctx.lineTo(e.target.x, e.target.y);

      if (e.provenance === 'INFERRED') {
        ctx.setLineDash([3, 4]);
      } else {
        ctx.setLineDash([]);
      }

      if (isConnected) {
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1.8;
      } else if (activeTarget) {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.02)';
        ctx.lineWidth = 0.8;
      } else {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
        ctx.lineWidth = 1.0;
      }
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // 2. Draw Nodes
    for (const n of this.simNodes) {
      if (n.community_id && vis[n.community_id] === false) continue;

      const isSel = n.id === selId;
      const isHov = n.id === hovId;
      const isNeighbor = activeTarget ? this.neighborSet.has(n.id) : false;
      const isCommHover = hovCommId && n.community_id === hovCommId;
      const isDimmed = activeTarget && !isSel && !isNeighbor;

      const color = n.community_color || '#38bdf8';

      // Outer glow for selected node
      if (isSel || isHov || isCommHover) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius + 5, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.25;
        ctx.fill();
      }

      // Main Node Circle
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.globalAlpha = isDimmed ? 0.12 : 1.0;
      ctx.fill();

      // Border ring
      ctx.strokeStyle = isSel ? '#ffffff' : color;
      ctx.lineWidth = isSel ? 2.5 : 1.0;
      ctx.globalAlpha = isDimmed ? 0.15 : 0.9;
      ctx.stroke();

      // Labels: show on selected, hovered, or major hub when zoomed in
      const showLabel = isSel || isHov || (this.scale > 1.3 && (n.degree || 0) >= 6);
      if (showLabel && !isDimmed) {
        this.drawNodeLabel(ctx, n);
      }
    }

    ctx.restore();
  }

  private drawNodeLabel(ctx: CanvasRenderingContext2D, n: SimNode): void {
    ctx.save();
    ctx.font = '600 11px system-ui, -apple-system, sans-serif';
    const text = n.label;
    const metrics = ctx.measureText(text);
    const textW = metrics.width;
    const padding = 5;
    const boxW = textW + padding * 2;
    const boxH = 18;
    const boxX = n.x - boxW / 2;
    const boxY = n.y - n.radius - boxH - 4;

    // Badge Background
    ctx.fillStyle = '#0f172a';
    ctx.globalAlpha = 0.88;
    ctx.beginPath();
    ctx.roundRect(boxX, boxY, boxW, boxH, 4);
    ctx.fill();

    // Badge Border
    ctx.strokeStyle = n.community_color || '#38bdf8';
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.8;
    ctx.stroke();

    // Text
    ctx.fillStyle = '#f8fafc';
    ctx.globalAlpha = 1.0;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, n.x, boxY + boxH / 2);
    ctx.restore();
  }

  // Canvas Mouse & Interaction Handlers
  onCanvasMouseDown(event: MouseEvent): void {
    const canvas = this.canvasRef?.nativeElement;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = (event.clientX - rect.left - this.panX) / this.scale;
    const my = (event.clientY - rect.top - this.panY) / this.scale;

    const hit = this.findNodeAt(mx, my);
    if (hit) {
      this.draggedNode = hit;
      this.selectNode(hit.id);
      this.simAlpha = 0.3;
    } else {
      this.isPanning = true;
      this.panStartX = event.clientX - this.panX;
      this.panStartY = event.clientY - this.panY;
    }
  }

  onCanvasMouseMove(event: MouseEvent): void {
    const canvas = this.canvasRef?.nativeElement;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = (event.clientX - rect.left - this.panX) / this.scale;
    const my = (event.clientY - rect.top - this.panY) / this.scale;

    if (this.draggedNode) {
      this.draggedNode.x = mx;
      this.draggedNode.y = my;
      this.draggedNode.vx = 0;
      this.draggedNode.vy = 0;
      this.simAlpha = Math.max(this.simAlpha, 0.2);
    } else if (this.isPanning) {
      this.panX = event.clientX - this.panStartX;
      this.panY = event.clientY - this.panStartY;
    } else {
      const hit = this.findNodeAt(mx, my);
      if (hit) {
        this.hoveredNodeId.set(hit.id);
        canvas.style.cursor = 'pointer';
      } else {
        this.hoveredNodeId.set(null);
        canvas.style.cursor = 'default';
      }
    }
  }

  onCanvasMouseUp(): void {
    this.isPanning = false;
    this.draggedNode = null;
  }

  onCanvasWheel(event: WheelEvent): void {
    event.preventDefault();
    const canvas = this.canvasRef?.nativeElement;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;

    const zoomFactor = event.deltaY < 0 ? 1.15 : 0.88;
    const newScale = Math.max(0.25, Math.min(4.0, this.scale * zoomFactor));

    this.panX = mouseX - (mouseX - this.panX) * (newScale / this.scale);
    this.panY = mouseY - (mouseY - this.panY) * (newScale / this.scale);
    this.scale = newScale;
  }

  onCanvasDblClick(event: MouseEvent): void {
    const canvas = this.canvasRef?.nativeElement;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = (event.clientX - rect.left - this.panX) / this.scale;
    const my = (event.clientY - rect.top - this.panY) / this.scale;
    const hit = this.findNodeAt(mx, my);
    if (hit) {
      this.expandNeighbors(hit.id);
    }
  }

  private findNodeAt(x: number, y: number): SimNode | null {
    const vis = this.communityVisibility();
    for (let i = this.simNodes.length - 1; i >= 0; i--) {
      const n = this.simNodes[i];
      if (n.community_id && vis[n.community_id] === false) continue;
      const dx = n.x - x;
      const dy = n.y - y;
      if (dx * dx + dy * dy <= (n.radius + 5) * (n.radius + 5)) {
        return n;
      }
    }
    return null;
  }

  // Node Selection & Focus
  selectNode(nodeId: string): void {
    this.selectedNodeId.set(nodeId);
    this.neighborSet.clear();

    for (const e of this.simEdges) {
      if (e.source.id === nodeId) this.neighborSet.add(e.target.id);
      if (e.target.id === nodeId) this.neighborSet.add(e.source.id);
    }

    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;

    this.nodeDetailLoading.set(true);
    this.riService
      .getNodeDetails(pid, rid, nodeId, this.selectedBranch())
      .subscribe({
        next: (res) => {
          this.selectedNodeDetail.set(res);
          this.nodeDetailLoading.set(false);
        },
        error: () => {
          this.nodeDetailLoading.set(false);
        },
      });
  }

  focusNodeInCanvas(nodeId: string): void {
    this.selectNode(nodeId);
    const node = this.nodeMap.get(nodeId);
    const canvas = this.canvasRef?.nativeElement;
    if (node && canvas) {
      // Unhide node's community if hidden
      if (node.community_id) {
        const curVis = { ...this.communityVisibility() };
        curVis[node.community_id] = true;
        this.communityVisibility.set(curVis);
      }
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      this.scale = 1.4;
      this.panX = w / 2 - node.x * this.scale;
      this.panY = h / 2 - node.y * this.scale;
      this.simAlpha = 0.3;
    }
  }

  // Community Controls
  toggleCommunity(commId: string): void {
    const cur = { ...this.communityVisibility() };
    cur[commId] = !cur[commId];
    this.communityVisibility.set(cur);
    const allVis = Object.values(cur).every(Boolean);
    this.selectAllCommunities.set(allVis);
    this.simAlpha = 0.3;
  }

  toggleAllCommunities(): void {
    const nextState = !this.selectAllCommunities();
    this.selectAllCommunities.set(nextState);
    const cur: Record<string, boolean> = {};
    for (const c of this.communities()) {
      cur[c.id] = nextState;
    }
    this.communityVisibility.set(cur);
    this.simAlpha = 0.3;
  }

  isolateCommunity(commId: string, event: MouseEvent): void {
    event.stopPropagation();
    const cur: Record<string, boolean> = {};
    for (const c of this.communities()) {
      cur[c.id] = c.id === commId;
    }
    this.communityVisibility.set(cur);
    this.selectAllCommunities.set(false);
    this.simAlpha = 0.3;
  }

  // Graph Layout Controls
  zoomIn(): void {
    this.scale = Math.min(4.0, this.scale * 1.25);
  }

  zoomOut(): void {
    this.scale = Math.max(0.25, this.scale * 0.8);
  }

  resetZoom(): void {
    this.scale = 1.0;
    this.panX = 0;
    this.panY = 0;
    this.simAlpha = 0.5;
  }

  fitGraph(): void {
    const canvas = this.canvasRef?.nativeElement;
    if (!canvas || this.simNodes.length === 0) return;
    const vis = this.communityVisibility();
    const visibleNodes = this.simNodes.filter(
      (n) => !n.community_id || vis[n.community_id] !== false
    );
    if (visibleNodes.length === 0) return;

    let minX = Infinity,
      maxX = -Infinity,
      minY = Infinity,
      maxY = -Infinity;
    for (const n of visibleNodes) {
      if (n.x < minX) minX = n.x;
      if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.y > maxY) maxY = n.y;
    }

    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const graphW = Math.max(100, maxX - minX + 80);
    const graphH = Math.max(100, maxY - minY + 80);

    const fitScale = Math.min(2.0, Math.min(w / graphW, h / graphH));
    this.scale = fitScale;
    this.panX = w / 2 - ((minX + maxX) / 2) * fitScale;
    this.panY = h / 2 - ((minY + maxY) / 2) * fitScale;
  }

  setLayoutMode(m: LayoutMode): void {
    this.layoutMode.set(m);
    this.simAlpha = 0.8;
  }

  expandNeighbors(nodeId: string): void {
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;

    this.riService
      .getNodeNeighbors(pid, rid, nodeId, this.selectedBranch())
      .subscribe({
        next: (res) => {
          const current = this.graphData();
          if (!current) return;
          const existingIds = new Set(current.nodes.map((n) => n.id));
          const newNodes = res.nodes.filter((n) => !existingIds.has(n.id));
          const existingEdgeKeys = new Set(
            current.edges.map((e) => `${e.source}->${e.target}:${e.type}`)
          );
          const newEdges = res.edges.filter(
            (e) => !existingEdgeKeys.has(`${e.source}->${e.target}:${e.type}`)
          );

          if (newNodes.length > 0 || newEdges.length > 0) {
            this.graphData.set({
              ...current,
              nodes: [...current.nodes, ...newNodes],
              edges: [...current.edges, ...newEdges],
              total_nodes: current.nodes.length + newNodes.length,
              total_edges: current.edges.length + newEdges.length,
            });
            this.initCanvasSimulation();
          }
        },
      });
  }

  analyzeImpactForNode(nodeId: string): void {
    this.impactTargetId.set(nodeId);
    this.tab.set('impact');
    this.runImpactAnalysis();
  }

  // 3. Search
  setSearchMode(mode: string): void {
    this.searchMode.set(mode as 'all' | 'file' | 'symbol' | 'code' | 'intent');
    this.executeSearch();
  }

  executeSearch(): void {
    const q = this.searchQuery().trim();
    if (!q) return;
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;

    this.searching.set(true);
    this.riService
      .search(pid, rid, q, this.searchMode(), this.selectedBranch())
      .subscribe({
        next: (res) => {
          this.searchResults.set(res.results);
          this.searching.set(false);
        },
        error: () => {
          this.searching.set(false);
          this.errorMessage.set('Search failed');
        },
      });
  }

  viewInGraph(nodeId: string | null | undefined): void {
    if (!nodeId) return;
    this.tab.set('graph');
    setTimeout(() => this.focusNodeInCanvas(nodeId), 150);
  }

  // 4. Dependencies
  loadDependencies(): void {
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;
    this.loading.set(true);
    this.riService.getDependencies(pid, rid, this.selectedBranch()).subscribe({
      next: (res) => {
        this.dependenciesData.set(res);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  // 5. Impact Analysis
  runImpactAnalysis(): void {
    const target = this.impactTargetId().trim();
    if (!target) return;
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;

    this.impactLoading.set(true);
    this.riService
      .getImpactAnalysis(pid, rid, target, this.selectedBranch())
      .subscribe({
        next: (res) => {
          this.impactData.set(res);
          this.impactLoading.set(false);
        },
        error: () => {
          this.impactLoading.set(false);
          this.errorMessage.set('Impact analysis failed');
        },
      });
  }

  // 6. History
  loadHistory(): void {
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;
    this.loading.set(true);
    this.riService.getHistory(pid, rid).subscribe({
      next: (res) => {
        this.historyData.set(res);
        this.loading.set(false);
        if (res.runs.length >= 2) {
          this.selectedRunA.set(res.runs[1].id);
          this.selectedRunB.set(res.runs[0].id);
        }
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  compareRuns(): void {
    const pid = this.selectedProjectId();
    const runA = this.selectedRunA();
    const runB = this.selectedRunB();
    if (!pid || !runA || !runB) return;

    this.diffLoading.set(true);
    this.riService.diffHistory(pid, runA, runB).subscribe({
      next: (res) => {
        this.diffData.set(res);
        this.diffLoading.set(false);
      },
      error: () => {
        this.diffLoading.set(false);
      },
    });
  }

  // 7. Indexing
  loadIndexing(): void {
    const hist = this.historyData();
    if (hist && hist.runs.length > 0) {
      this.fetchRunDetail(hist.runs[0].id);
    } else {
      this.riService
        .getHistory(this.selectedProjectId(), this.selectedRepoId())
        .subscribe({
          next: (res) => {
            if (res.runs.length > 0) {
              this.fetchRunDetail(res.runs[0].id);
            }
          },
        });
    }
  }

  fetchRunDetail(runId: string): void {
    this.riService.getIndexRunDetail(this.selectedProjectId(), runId).subscribe({
      next: (detail) => {
        this.liveRunDetail.set(detail);
      },
    });
  }

  triggerIndexing(): void {
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;

    this.indexing.set(true);
    this.errorMessage.set('');
    this.successMessage.set('');

    this.riService
      .triggerIndex(pid, rid, this.selectedBranch(), this.indexForce())
      .subscribe({
        next: (res) => {
          this.indexing.set(false);
          if (res.status === 'COMPLETED') {
            this.successMessage.set('Indexing finished successfully.');
          } else {
            this.errorMessage.set(res.message || `Indexing finished with status: ${res.status}`);
          }
          this.fetchRunDetail(res.run_id);
          this.loadOverview();
          this.loadActiveTab();
        },
        error: (err) => {
          this.indexing.set(false);
          this.errorMessage.set(err?.error?.detail || 'Indexing failed');
        },
      });
  }

  // 8. Settings
  loadSettings(): void {
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;

    this.loading.set(true);
    this.riService.getSettings(pid, rid).subscribe({
      next: (res) => {
        this.settingsData.set(res);
        this.settingsDefaultBranch = res.default_branch;
        this.settingsIncludedPaths = res.included_paths.join(', ');
        this.settingsExcludedPaths = res.excluded_paths.join(', ');
        this.settingsMaxFileSizeKb = res.max_file_size_kb;
        this.settingsAutoIndex = res.auto_index_on_sync;
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
      },
    });
  }

  saveSettings(): void {
    const pid = this.selectedProjectId();
    const rid = this.selectedRepoId();
    if (!pid || !rid) return;

    this.settingsSaving.set(true);
    this.errorMessage.set('');
    this.successMessage.set('');

    const inc = this.settingsIncludedPaths
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const exc = this.settingsExcludedPaths
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    this.riService
      .updateSettings(pid, {
        repository_connection_id: rid,
        default_branch: this.settingsDefaultBranch,
        included_paths: inc,
        excluded_paths: exc,
        max_file_size_kb: this.settingsMaxFileSizeKb,
        auto_index_on_sync: this.settingsAutoIndex,
      })
      .subscribe({
        next: (res) => {
          this.settingsData.set(res);
          this.settingsSaving.set(false);
          this.successMessage.set('Settings saved successfully.');
        },
        error: () => {
          this.settingsSaving.set(false);
          this.errorMessage.set('Failed to save settings.');
        },
      });
  }

  getNodeColor(type: string): string {
    switch (type) {
      case 'File':
        return '#3b82f6';
      case 'Directory':
        return '#8b5cf6';
      case 'Class':
        return '#10b981';
      case 'Function':
      case 'Method':
        return '#06b6d4';
      case 'API':
        return '#f59e0b';
      case 'Test':
        return '#ec4899';
      case 'External':
        return '#64748b';
      default:
        return '#6366f1';
    }
  }
}
