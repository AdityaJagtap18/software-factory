import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

type ProvTab = 'overview' | 'providers' | 'models' | 'routing' | 'quotas' | 'cost' | 'audit';

@Component({
  selector: 'sf-providers',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './providers.component.html',
  styleUrl: './providers.component.scss'
})
export class ProvidersComponent {
  private readonly data = inject(MockDataService);
  readonly providers = this.data.providers;
  readonly models = this.data.modelCatalog;

  tab = signal<ProvTab>('overview');

  readonly routingPolicies = [
    { name: 'Coding Tasks', description: 'Software implementation, refactoring, tests', primary: 'Claude 3.7', fallback: 'GPT-5 (fallback)' },
    { name: 'Planning & Design', description: 'Requirement analysis, architectural design', primary: 'Gemini 2.5 Pro', fallback: 'Claude (fallback)' },
    { name: 'Agent Reasoning', description: 'Multi-step tool use, workflow orchestration', primary: 'GPT-5', fallback: 'Qwen3 (fallback)' },
    { name: 'General Q&A', description: 'Documentation, explanations, summaries', primary: 'Qwen3 14B', fallback: 'Llama 3.1 (fallback)' }
  ];

  readonly quotas = [
    { name: 'OpenAI', icon: 'providers/cloud-provider', pct: 61, usage: '7.9M / 13M tokens' },
    { name: 'Anthropic', icon: 'providers/cloud-provider', pct: 42, usage: '4.2M / 10M tokens' },
    { name: 'Google', icon: 'providers/cloud-provider', pct: 68, usage: '6.8M / 10M tokens' },
    { name: 'Ollama (Local)', icon: 'providers/local-model', pct: 0, usage: 'No limit' }
  ];
}
