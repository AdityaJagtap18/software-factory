import { Routes } from '@angular/router';
import { AppShellComponent } from './core/layout/app-shell.component';
import { authGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login.component').then((m) => m.LoginComponent)
  },
  {
    path: '',
    component: AppShellComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        loadComponent: () => import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent)
      },
      {
        path: 'projects',
        loadComponent: () => import('./features/projects/projects-list.component').then((m) => m.ProjectsListComponent)
      },
      {
        path: 'projects/:projectId',
        loadComponent: () => import('./features/project-workspace/project-workspace.component').then((m) => m.ProjectWorkspaceComponent)
      },
      {
        path: 'projects/:projectId/repository-intelligence',
        loadComponent: () => import('./features/repository-intelligence/repository-intelligence.component').then((m) => m.RepositoryIntelligenceComponent)
      },
      {
        path: 'tasks',
        loadComponent: () => import('./features/task-workspace/task-workspace.component').then((m) => m.TaskWorkspaceComponent)
      },
      {
        path: 'tasks/:taskId',
        loadComponent: () => import('./features/task-workspace/task-workspace.component').then((m) => m.TaskWorkspaceComponent)
      },
      {
        path: 'tasks/:taskId/review',
        loadComponent: () => import('./features/code-review/code-review.component').then((m) => m.CodeReviewComponent)
      },
      {
        path: 'repositories',
        loadComponent: () => import('./features/repository-intelligence/repository-intelligence.component').then((m) => m.RepositoryIntelligenceComponent)
      },
      {
        path: 'workflows',
        loadComponent: () => import('./features/workflows/workflow-detail.component').then((m) => m.WorkflowDetailComponent)
      },
      {
        path: 'agents',
        loadComponent: () => import('./features/agents/agents.component').then((m) => m.AgentsComponent)
      },
      {
        path: 'prompts',
        loadComponent: () => import('./features/prompts/prompts.component').then((m) => m.PromptsComponent)
      },
      {
        path: 'knowledge',
        loadComponent: () => import('./features/knowledge/knowledge-graph.component').then((m) => m.KnowledgeGraphComponent)
      },
      {
        path: 'artifacts',
        loadComponent: () => import('./features/artifacts/artifacts.component').then((m) => m.ArtifactsComponent)
      },
      {
        path: 'approvals',
        loadComponent: () => import('./features/approvals/approvals.component').then((m) => m.ApprovalsComponent)
      },
      {
        path: 'monitoring',
        loadComponent: () => import('./features/monitoring/monitoring.component').then((m) => m.MonitoringComponent)
      },
      {
        path: 'providers',
        loadComponent: () => import('./features/providers/providers.component').then((m) => m.ProvidersComponent)
      },
      {
        path: 'settings',
        loadComponent: () => import('./features/settings/settings.component').then((m) => m.SettingsComponent)
      }
    ]
  },
  { path: '**', redirectTo: 'dashboard' }
];
