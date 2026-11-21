import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IconComponent } from '../../shared/icon/icon.component';
import { AuditLogService } from '../../core/org/audit-log.service';
import { OrganizationService } from '../../core/org/organization.service';

@Component({
  selector: 'sf-audit-log',
  standalone: true,
  imports: [CommonModule, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './audit-log.component.html',
  styleUrl: './audit-log.component.scss'
})
export class AuditLogComponent {
  private readonly auditLogService = inject(AuditLogService);
  private readonly orgService = inject(OrganizationService);

  readonly entries = this.auditLogService.entries;
  readonly loaded = this.auditLogService.loaded;
  readonly actionFilter = signal('');
  readonly targetTypeFilter = signal('');

  private organizationId = '';

  constructor() {
    this.orgService.listMine().subscribe({
      next: (orgs) => {
        if (orgs.length > 0) {
          this.organizationId = this.orgService.activeOrgId() || orgs[0].id;
          this.refresh();
        }
      }
    });
  }

  refresh(): void {
    if (!this.organizationId) return;
    this.auditLogService
      .listForOrg(this.organizationId, {
        action: this.actionFilter().trim() || undefined,
        target_type: this.targetTypeFilter().trim() || undefined
      })
      .subscribe();
  }

  setActionFilter(value: string): void {
    this.actionFilter.set(value);
  }

  setTargetTypeFilter(value: string): void {
    this.targetTypeFilter.set(value);
  }
}
