import { ChangeDetectionStrategy, Component, OnInit, computed, effect, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { IconComponent } from '../../shared/icon/icon.component';
import { OrganizationService } from '../../core/org/organization.service';
import { ProjectService } from '../../core/org/project.service';
import { GitIntegrationService } from '../../core/org/git-integration.service';
import { RepositorySummary } from '../../core/org/git-integration.models';

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
  private readonly gitService = inject(GitIntegrationService);
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

  readonly gitInstallations = this.gitService.installations;
  readonly createInstallationId = signal('');
  readonly createRepositories = signal<RepositorySummary[]>([]);
  readonly loadingCreateRepositories = signal(false);
  readonly createRepoError = signal('');
  readonly selectedRepoFullName = signal('');
  readonly repoFilterTerm = signal('');

  readonly filteredCreateRepositories = computed(() => {
    const term = this.repoFilterTerm().toLowerCase().trim();
    const repos = this.createRepositories();
    if (!term) return repos;
    return repos.filter((r) => r.full_name.toLowerCase().includes(term));
  });

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
        this.gitService.listInstallations(orgId).subscribe();
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
    this.createRepositories.set([]);
    this.createRepoError.set('');
    this.selectedRepoFullName.set('');
    this.repoFilterTerm.set('');
    const firstInstallation = this.gitInstallations()[0];
    this.createInstallationId.set(firstInstallation?.id ?? '');
    this.showCreate.set(true);
    if (firstInstallation) this.loadCreateRepositories();
  }

  closeCreate() {
    this.showCreate.set(false);
  }

  onCreateInstallationChange(installationId: string) {
    this.createInstallationId.set(installationId);
    this.selectedRepoFullName.set('');
    this.loadCreateRepositories();
  }

  private loadCreateRepositories() {
    const orgId = this.orgService.activeOrgId();
    const installationId = this.createInstallationId();
    if (!orgId || !installationId) return;
    this.loadingCreateRepositories.set(true);
    this.createRepoError.set('');
    this.gitService.listInstallationRepositories(orgId, installationId).subscribe({
      next: (repos) => {
        this.createRepositories.set(repos);
        this.loadingCreateRepositories.set(false);
      },
      error: (err) => {
        this.createRepositories.set([]);
        this.loadingCreateRepositories.set(false);
        this.createRepoError.set(err?.error?.detail ?? 'Could not list repositories for this installation.');
      }
    });
  }

  onSelectRepo(fullName: string) {
    this.selectedRepoFullName.set(fullName);
    const repo = this.createRepositories().find((r) => r.full_name === fullName);
    if (repo && !this.newProjectName().trim()) {
      this.newProjectName.set(repo.name);
    }
  }

  submitCreate() {
    const orgId = this.orgService.activeOrgId();
    const name = this.newProjectName().trim();
    if (!orgId || !name) return;
    this.creating.set(true);
    this.createRepoError.set('');
    const repo = this.createRepositories().find((r) => r.full_name === this.selectedRepoFullName());
    const installationId = this.createInstallationId();

    this.projectService
      .create(orgId, {
        name,
        description: this.newProjectDescription().trim(),
        repository_url: repo ? `github.com/${repo.full_name}` : this.newProjectRepo().trim()
      })
      .subscribe({
        next: (project) => {
          if (repo && installationId) {
            this.gitService
              .createRepositoryConnection(project.id, {
                git_installation_id: installationId,
                owner: repo.owner,
                name: repo.name
              })
              .subscribe({
                complete: () => {
                  this.creating.set(false);
                  this.showCreate.set(false);
                  this.router.navigate(['/projects', project.id]);
                },
                error: () => {
                  this.creating.set(false);
                  this.showCreate.set(false);
                  this.router.navigate(['/projects', project.id]);
                }
              });
          } else {
            this.creating.set(false);
            this.showCreate.set(false);
            this.router.navigate(['/projects', project.id]);
          }
        },
        error: () => this.creating.set(false)
      });
  }
}
