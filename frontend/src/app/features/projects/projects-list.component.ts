import { ChangeDetectionStrategy, Component, OnInit, computed, effect, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { OrganizationService } from '../../core/org/organization.service';
import { ProjectService } from '../../core/org/project.service';

@Component({
  selector: 'sf-projects-list',
  standalone: true,
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './projects-list.component.html',
  styleUrl: './projects-list.component.scss'
})
export class ProjectsListComponent implements OnInit {
  private readonly orgService = inject(OrganizationService);
  private readonly projectService = inject(ProjectService);
  private readonly router = inject(Router);

  readonly allProjects = this.projectService.projects;
  readonly loaded = this.projectService.loaded;

  search = signal('');
  statusFilter = signal<'All' | 'Active' | 'In Progress' | 'Paused' | 'Archived'>('All');

  readonly showCreate = signal(false);
  readonly newProjectName = signal('');
  readonly newProjectDescription = signal('');
  readonly newProjectRepo = signal('');
  readonly creating = signal(false);

  readonly projects = computed(() => {
    const term = this.search().toLowerCase();
    return this.allProjects().filter((p) => {
      const matchesTerm =
        !term || p.name.toLowerCase().includes(term) || p.description.toLowerCase().includes(term);
      const matchesStatus = this.statusFilter() === 'All' || p.status === this.statusFilter();
      return matchesTerm && matchesStatus;
    });
  });

  constructor() {
    effect(() => {
      const orgId = this.orgService.activeOrgId();
      if (orgId) {
        this.projectService.listForOrg(orgId).subscribe();
      }
    });
  }

  ngOnInit(): void {
    if (this.orgService.organizations().length === 0) {
      this.orgService.listMine().subscribe();
    }
  }

  statusTone(status: string): 'green' | 'blue' | 'amber' | 'gray' {
    if (status === 'Active') return 'green';
    if (status === 'In Progress') return 'blue';
    if (status === 'Paused') return 'amber';
    return 'gray';
  }

  openCreate() {
    this.newProjectName.set('');
    this.newProjectDescription.set('');
    this.newProjectRepo.set('');
    this.showCreate.set(true);
  }

  closeCreate() {
    this.showCreate.set(false);
  }

  submitCreate() {
    const orgId = this.orgService.activeOrgId();
    const name = this.newProjectName().trim();
    if (!orgId || !name) return;
    this.creating.set(true);
    this.projectService
      .create(orgId, {
        name,
        description: this.newProjectDescription().trim(),
        repository_url: this.newProjectRepo().trim()
      })
      .subscribe({
        next: (project) => {
          this.creating.set(false);
          this.showCreate.set(false);
          this.router.navigate(['/projects', project.id]);
        },
        error: () => this.creating.set(false)
      });
  }
}
