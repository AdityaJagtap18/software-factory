import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { ApprovalService } from '../../core/org/approval.service';
import { ProjectService } from '../../core/org/project.service';
import { OrganizationService } from '../../core/org/organization.service';
import { ApiApproval, ApprovalCategory } from '../../core/org/approval.models';

type ApprovalsTab = 'all' | ApprovalCategory;

const TAB_CATEGORY: Record<ApprovalsTab, ApprovalCategory | null> = {
  all: null,
  code_change: 'code_change',
  workflow_run: 'workflow_run',
  knowledge_update: 'knowledge_update',
  prompt_change: 'prompt_change',
  model_action: 'model_action',
  access_security: 'access_security'
};

@Component({
  selector: 'sf-approvals',
  standalone: true,
  imports: [CommonModule, RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './approvals.component.html',
  styleUrl: './approvals.component.scss'
})
export class ApprovalsComponent {
  private readonly approvalService = inject(ApprovalService);
  private readonly projectService = inject(ProjectService);
  private readonly orgService = inject(OrganizationService);

  readonly projects = this.projectService.projects;
  readonly selectedProjectId = signal<string>('');
  readonly loaded = this.approvalService.loaded;

  readonly allApprovals = this.approvalService.approvals;
  readonly tab = signal<ApprovalsTab>('all');
  readonly selectedId = signal<string | null>(null);
  readonly decisionError = signal<string>('');
  readonly deciding = signal<boolean>(false);

  readonly pending = computed(() => this.allApprovals().filter((a) => a.status === 'pending'));
  readonly decided = computed(() => this.allApprovals().filter((a) => a.status !== 'pending'));
  readonly approvedCount = computed(() => this.allApprovals().filter((a) => a.status === 'approved').length);
  readonly rejectedCount = computed(() => this.allApprovals().filter((a) => a.status === 'rejected').length);

  readonly visible = computed(() => {
    const category = TAB_CATEGORY[this.tab()];
    const list = this.pending();
    return category ? list.filter((a) => a.category === category) : list;
  });

  readonly selected = computed<ApiApproval | null>(() => {
    const id = this.selectedId();
    return this.visible().find((a) => a.id === id) ?? this.visible()[0] ?? null;
  });

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
  }

  selectProject(projectId: string): void {
    this.selectedProjectId.set(projectId);
    this.selectedId.set(null);
    this.approvalService.listForProject(projectId).subscribe();
  }

  select(a: ApiApproval): void {
    this.selectedId.set(a.id);
    this.decisionError.set('');
  }

  decide(decision: 'approved' | 'rejected' | 'changes_requested'): void {
    const approval = this.selected();
    const projectId = this.selectedProjectId();
    if (!approval || !projectId) return;
    this.deciding.set(true);
    this.decisionError.set('');
    this.approvalService.decide(projectId, approval.id, { decision }).subscribe({
      next: () => {
        this.deciding.set(false);
        this.selectedId.set(null);
      },
      error: (err) => {
        this.deciding.set(false);
        this.decisionError.set(err?.error?.detail || 'Could not record this decision.');
      }
    });
  }

  priorityTone(priority: string): 'red' | 'amber' | 'gray' {
    if (priority === 'high') return 'red';
    if (priority === 'medium') return 'amber';
    return 'gray';
  }

  categoryIcon(category: ApprovalCategory): string {
    switch (category) {
      case 'code_change':
        return 'workspace/pull-request';
      case 'workflow_run':
        return 'navigation/workflows';
      case 'knowledge_update':
        return 'navigation/knowledge';
      case 'prompt_change':
        return 'agents/coding-agent';
      case 'model_action':
        return 'navigation/providers';
      case 'access_security':
        return 'navigation/settings';
      default:
        return 'navigation/approvals';
    }
  }

  categoryLabel(category: ApprovalCategory): string {
    switch (category) {
      case 'code_change':
        return 'Code Change';
      case 'workflow_run':
        return 'Workflow Run';
      case 'knowledge_update':
        return 'Knowledge';
      case 'prompt_change':
        return 'Agent / Prompt';
      case 'model_action':
        return 'Model / Agent Action';
      case 'access_security':
        return 'Access & Security';
      default:
        return category;
    }
  }
}
