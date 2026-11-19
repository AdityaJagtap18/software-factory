import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { IconComponent } from '../../shared/icon/icon.component';
import { MockDataService } from '../../core/mock-data.service';

type DetailTab = 'conversation' | 'files' | 'diff' | 'execution' | 'timeline';
type TaskListTab = 'my' | 'all' | 'history';

@Component({
  selector: 'sf-task-workspace',
  standalone: true,
  imports: [RouterLink, IconComponent, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './task-workspace.component.html',
  styleUrl: './task-workspace.component.scss'
})
export class TaskWorkspaceComponent {
  private readonly data = inject(MockDataService);
  private readonly route = inject(ActivatedRoute);

  private readonly params = toSignal(this.route.paramMap, { initialValue: this.route.snapshot.paramMap });

  readonly allTasks = this.data.tasks;
  readonly selectedTask = computed(() => {
    const id = this.params()?.get('taskId');
    return this.allTasks().find((t) => t.id === id) ?? this.allTasks()[0];
  });

  readonly steps = this.data.taskExecutionSteps;
  readonly conversation = this.data.conversation;
  readonly executionPlan = this.data.taskExecutionPlan;
  readonly agentBreakdown = this.data.taskAgentBreakdown;
  readonly codeChanges = this.data.codeChanges;

  listTab = signal<TaskListTab>('my');
  detailTab = signal<DetailTab>('conversation');
  draftMessage = signal('');

  send() {
    if (!this.draftMessage().trim()) return;
    this.conversation.update((msgs) => [
      ...msgs,
      { id: 'm' + (msgs.length + 1), author: 'You', authorKind: 'user', timestamp: 'now', body: this.draftMessage() }
    ]);
    this.draftMessage.set('');
  }

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'Completed') return 'green';
    if (status === 'In Progress') return 'blue';
    if (status === 'Pending Review') return 'amber';
    return 'gray';
  }
}
