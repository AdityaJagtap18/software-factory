import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

type TopTab = 'general' | 'agents' | 'models' | 'integrations' | 'execution' | 'workflows' | 'security' | 'governance' | 'preferences';

@Component({
  selector: 'sf-settings',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss'
})
export class SettingsComponent {
  private readonly data = inject(MockDataService);
  readonly runtimes = this.data.codingAgentRuntimes;

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

  statusTone(status: string): 'green' | 'gray' | 'amber' {
    if (status === 'Connected') return 'green';
    if (status === 'Not connected') return 'amber';
    return 'gray';
  }
}
