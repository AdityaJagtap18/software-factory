import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, effect, inject, signal } from '@angular/core';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';
import { OrganizationService } from '../../core/org/organization.service';
import { AgentRuntimeService } from '../../core/org/agent-runtime.service';
import { AgentConnection, ConnectionMode } from '../../core/org/agent-runtime.models';

type TopTab = 'general' | 'agents' | 'models' | 'integrations' | 'execution' | 'workflows' | 'security' | 'governance' | 'preferences';

@Component({
  selector: 'sf-settings',
  standalone: true,
  imports: [IconComponent, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss'
})
export class SettingsComponent implements OnInit {
  private readonly data = inject(MockDataService);
  private readonly orgService = inject(OrganizationService);
  private readonly runtimeService = inject(AgentRuntimeService);

  readonly connections = this.runtimeService.connections;
  readonly connectionsLoaded = this.runtimeService.loaded;

  topTab = signal<TopTab>('integrations');

  readonly agentSettingsList = [
    { name: 'Coding Agent', icon: 'agents/coding-agent' },
    { name: 'Planning Agent', icon: 'agents/planning-agent' },
    { name: 'Review Agent', icon: 'agents/review-agent' },
    { name: 'Testing Agent', icon: 'agents/testing-agent' },
    { name: 'Documentation Agent', icon: 'agents/documentation-agent' },
    { name: 'QA Agent', icon: 'agents/testing-agent' },
    { name: 'Custom Agents', icon: 'agents/supervisor-agent' }
  ];
  selectedAgent = signal(this.agentSettingsList[0]);

  readonly capabilities = [
    { label: 'Implement new features', enabled: true },
    { label: 'Modify / refactor code', enabled: true },
    { label: 'Generate unit & integration tests', enabled: true },
    { label: 'Update documentation (README, API, etc.)', enabled: true },
    { label: 'Create pull requests', enabled: true },
    { label: 'Fix build / test failures', enabled: true },
    { label: 'Code review (self-check)', enabled: true }
  ];

  readonly guardrails = [
    { label: 'Enforce coding standards', enabled: true },
    { label: 'Run security scan (SAST)', enabled: true },
    { label: 'Check license compliance', enabled: true },
    { label: 'Apply project guardrails', enabled: true },
    { label: 'Block high-risk operations', enabled: true }
  ];

  readonly connectTarget = signal<AgentConnection | null>(null);
  readonly connectMode = signal<ConnectionMode>('local_runtime');
  readonly credentialValue = signal('');
  readonly connecting = signal(false);
  readonly connectError = signal('');
  readonly recheckingId = signal<string | null>(null);

  constructor() {
    effect(() => {
      const orgId = this.orgService.activeOrgId();
      if (orgId) {
        this.runtimeService.listForOrg(orgId).subscribe();
      }
    });
  }

  ngOnInit(): void {
    if (this.orgService.organizations().length === 0) {
      this.orgService.listMine().subscribe();
    }
  }

  statusTone(status: string): 'green' | 'gray' | 'amber' | 'red' {
    if (status === 'connected') return 'green';
    if (status === 'not_connected') return 'amber';
    if (status === 'error') return 'red';
    return 'gray';
  }

  statusLabel(status: string): string {
    switch (status) {
      case 'connected': return 'Connected';
      case 'not_connected': return 'Not connected';
      case 'error': return 'Error';
      default: return 'Not configured';
    }
  }

  connectionModeLabel(mode: string | null): string {
    switch (mode) {
      case 'local_runtime': return 'Local runtime';
      case 'factory_managed': return 'Factory-managed';
      case 'custom_adapter': return 'Custom adapter';
      default: return '—';
    }
  }

  openConnect(entry: AgentConnection) {
    this.connectTarget.set(entry);
    this.connectMode.set('local_runtime');
    this.credentialValue.set('');
    this.connectError.set('');
  }

  closeConnect() {
    this.connectTarget.set(null);
  }

  submitConnect() {
    const orgId = this.orgService.activeOrgId();
    const target = this.connectTarget();
    if (!orgId || !target) return;

    this.connecting.set(true);
    this.connectError.set('');
    this.runtimeService
      .connect(orgId, {
        runtime_slug: target.runtime_slug,
        connection_mode: this.connectMode(),
        credential_value: this.credentialValue().trim() || undefined
      })
      .subscribe({
        next: () => {
          this.connecting.set(false);
          this.connectTarget.set(null);
        },
        error: (err) => {
          this.connecting.set(false);
          this.connectError.set(err?.error?.detail ?? 'Could not configure this connection.');
        }
      });
  }

  recheck(entry: AgentConnection) {
    const orgId = this.orgService.activeOrgId();
    if (!orgId || !entry.id) return;
    this.recheckingId.set(entry.id);
    this.runtimeService.recheck(orgId, entry.id).subscribe({
      complete: () => this.recheckingId.set(null)
    });
  }

  disconnect(entry: AgentConnection) {
    const orgId = this.orgService.activeOrgId();
    if (!orgId || !entry.id) return;
    this.runtimeService.disconnect(orgId, entry.id, entry.runtime_slug).subscribe();
  }
}
