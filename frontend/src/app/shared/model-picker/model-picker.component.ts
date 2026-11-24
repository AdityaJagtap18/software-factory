import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  input,
  output,
  signal,
  effect
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AgentRuntimeService } from '../../core/org/agent-runtime.service';
import {
  ModelCatalogResponse,
  ModelOption,
  ProviderGroup
} from '../../core/org/agent-runtime.models';
import { IconComponent } from '../icon/icon.component';

@Component({
  selector: 'sf-model-picker',
  standalone: true,
  imports: [CommonModule, FormsModule, IconComponent],
  templateUrl: './model-picker.component.html',
  styleUrl: './model-picker.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ModelPickerComponent {
  private readonly elementRef = inject(ElementRef);
  private readonly agentRuntimeService = inject(AgentRuntimeService);

  projectId = input.required<string>();
  taskId = input<string | undefined>();
  currentModelId = input<string | undefined>();
  disabled = input<boolean>(false);
  compact = input<boolean>(false);
  placement = input<'top' | 'bottom'>('top');

  modelSelected = output<ModelOption>();

  isOpen = signal<boolean>(false);
  loading = signal<boolean>(false);
  error = signal<string | null>(null);
  searchQuery = signal<string>('');
  catalog = signal<ModelCatalogResponse | null>(null);

  // Track the active model internally when set or updated
  activeModelId = signal<string>('');

  constructor() {
    effect(() => {
      const explicit = this.currentModelId();
      if (explicit) {
        this.activeModelId.set(explicit);
      }
    });

    effect(() => {
      const pId = this.projectId();
      if (pId) {
        this.loadCatalog(pId, this.taskId());
      }
    });
  }

  loadCatalog(projectId: string, taskId?: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.agentRuntimeService.getModelCatalog(projectId, taskId).subscribe({
      next: (cat) => {
        this.catalog.set(cat);
        this.loading.set(false);
        if (!this.activeModelId()) {
          const selected = cat.selected_model_id || cat.default_model_id;
          if (selected) {
            this.activeModelId.set(selected);
          }
        }
      },
      error: (err) => {
        this.error.set(err?.message || 'Failed to load model catalog');
        this.loading.set(false);
      }
    });
  }

  readonly selectedModel = computed<ModelOption | null>(() => {
    const cat = this.catalog();
    const id = this.activeModelId();
    if (!cat || !cat.models.length) return null;

    if (id) {
      // Check composite ID match first, then model_id match, then runtime_slug match
      const exactMatch = cat.models.find((m) => m.id === id);
      if (exactMatch) return exactMatch;

      const modelIdMatch = cat.models.find((m) => m.model_id === id);
      if (modelIdMatch) return modelIdMatch;

      const runtimeMatch = cat.models.find((m) => m.runtime_slug === id);
      if (runtimeMatch) return runtimeMatch;
    }

    // Default to first selected or first connected model
    const def = cat.models.find((m) => m.id === cat.selected_model_id) ||
                cat.models.find((m) => m.availability_status === 'CONNECTED') ||
                cat.models[0];
    return def || null;
  });

  readonly filteredGroups = computed<ProviderGroup[]>(() => {
    const cat = this.catalog();
    if (!cat) return [];
    const query = this.searchQuery().trim().toLowerCase();
    if (!query) return cat.groups;

    return cat.groups
      .map((group) => {
        const matchingModels = group.models.filter(
          (m) =>
            m.model_name.toLowerCase().includes(query) ||
            m.provider_name.toLowerCase().includes(query) ||
            m.runtime_name.toLowerCase().includes(query) ||
            m.display_name.toLowerCase().includes(query) ||
            (m.description && m.description.toLowerCase().includes(query))
        );
        return { ...group, models: matchingModels };
      })
      .filter((group) => group.models.length > 0);
  });

  togglePopover(): void {
    if (this.disabled()) return;
    const next = !this.isOpen();
    this.isOpen.set(next);
    if (next) {
      this.searchQuery.set('');
      if (!this.catalog()) {
        this.loadCatalog(this.projectId(), this.taskId());
      }
    }
  }

  selectModel(model: ModelOption): void {
    if (!model.selection_allowed) return;
    this.activeModelId.set(model.id);
    this.isOpen.set(false);
    this.modelSelected.emit(model);
  }

  isSelected(model: ModelOption): boolean {
    const current = this.selectedModel();
    if (!current) return false;
    return current.id === model.id || current.model_id === model.model_id;
  }

  getProviderIcon(providerId: string, runtimeSlug: string): string {
    if (runtimeSlug === 'ollama' || providerId === 'ollama' || providerId === 'local') {
      return 'providers/local-model';
    }
    if (runtimeSlug === 'claude_code' || runtimeSlug === 'claude-code') {
      return 'agents/coding-agent';
    }
    if (runtimeSlug === 'gemini_cli' || runtimeSlug === 'gemini-cli') {
      return 'navigation/agents';
    }
    return 'providers/cloud-provider';
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.isOpen()) return;
    const target = event.target as HTMLElement;
    if (!this.elementRef.nativeElement.contains(target)) {
      this.isOpen.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.isOpen()) {
      this.isOpen.set(false);
    }
  }
}
