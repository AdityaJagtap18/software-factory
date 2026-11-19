import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { IconComponent } from '../../shared/icon/icon.component';
import { WorkflowService } from '../../core/org/workflow.service';

@Component({
  selector: 'sf-workflow-detail',
  standalone: true,
  imports: [RouterLink, IconComponent, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './workflow-detail.component.html',
  styleUrl: './workflow-detail.component.scss'
})
export class WorkflowDetailComponent {
  private readonly workflowService = inject(WorkflowService);
  private readonly route = inject(ActivatedRoute);

  private readonly params = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });

  readonly workflows = this.workflowService.myWorkflows;
  readonly loaded = this.workflowService.myWorkflowsLoaded;

  readonly selectedWorkflow = computed(() => {
    const list = this.workflows();
    if (list.length === 0) return null;
    const id = this.params()?.get('workflowId');
    return list.find((w) => w.id === id) ?? list[0];
  });

  readonly progressPercent = computed(() => {
    const wf = this.selectedWorkflow();
    if (!wf || wf.steps.length === 0) return 0;
    return Math.round((100 * wf.current_step_index) / wf.steps.length);
  });

  readonly busy = signal(false);

  constructor() {
    this.workflowService.listMine().subscribe();
  }

  start(): void {
    const wf = this.selectedWorkflow();
    if (!wf) return;
    this.busy.set(true);
    this.workflowService.start(wf.project_id, wf.id).subscribe({
      complete: () => this.busy.set(false),
      error: () => this.busy.set(false)
    });
  }

  cancel(): void {
    const wf = this.selectedWorkflow();
    if (!wf) return;
    this.workflowService.cancel(wf.project_id, wf.id).subscribe();
  }

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'completed') return 'green';
    if (status === 'running') return 'blue';
    if (status === 'failed') return 'amber';
    return 'gray';
  }
}
