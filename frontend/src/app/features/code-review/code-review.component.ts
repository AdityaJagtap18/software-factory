import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

type ReviewTab = 'conversation' | 'changes' | 'tests' | 'quality' | 'artifacts' | 'logs';

@Component({
  selector: 'sf-code-review',
  standalone: true,
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './code-review.component.html',
  styleUrl: './code-review.component.scss'
})
export class CodeReviewComponent {
  private readonly data = inject(MockDataService);
  private readonly route = inject(ActivatedRoute);
  private readonly params = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });

  readonly task = computed(() => {
    const id = this.params()?.get('taskId');
    return this.data.tasks().find((t) => t.id === id) ?? this.data.tasks()[0];
  });

  readonly changes = this.data.codeChanges;
  readonly selectedFile = signal(this.changes()[0]);
  tab = signal<ReviewTab>('changes');

  readonly totals = computed(() => {
    const files = this.changes();
    return {
      added: files.reduce((s, f) => s + f.added, 0),
      removed: files.reduce((s, f) => s + f.removed, 0),
      files: files.length
    };
  });

  selectFile(file: ReturnType<typeof this.changes>[number]) {
    this.selectedFile.set(file);
  }
}
