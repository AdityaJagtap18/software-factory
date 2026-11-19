import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

interface ArtifactRow {
  name: string;
  type: string;
  project: string;
  task: string;
  size: string;
  createdAt: string;
  icon: string;
}

@Component({
  selector: 'sf-artifacts',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './artifacts.component.html',
  styleUrl: './artifacts.component.scss'
})
export class ArtifactsComponent {
  private readonly data = inject(MockDataService);

  readonly artifacts = computed<ArtifactRow[]>(() => {
    const changes = this.data.codeChanges();
    const projects = this.data.projects();
    return changes.map((c, i) => ({
      name: c.name,
      type: c.language === 'python' ? 'Source Code' : c.language === 'markdown' ? 'Documentation' : 'File',
      project: projects[i % projects.length].slug,
      task: 'TSK-4827',
      size: `${(4 + i * 3.2).toFixed(1)} KB`,
      createdAt: '18 Nov 2026',
      icon: c.icon
    }));
  });

  typeFilter = signal('All');
  readonly types = ['All', 'Source Code', 'Documentation', 'File'];

  readonly filtered = computed(() =>
    this.artifacts().filter((a) => this.typeFilter() === 'All' || a.type === this.typeFilter())
  );
}
