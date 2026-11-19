export interface NavItem {
  label: string;
  icon: string;
  route: string;
  badge?: number;
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', icon: 'navigation/dashboard', route: '/dashboard' },
  { label: 'Projects', icon: 'navigation/projects', route: '/projects' },
  { label: 'Task Center', icon: 'navigation/tasks', route: '/tasks' },
  { label: 'Repositories', icon: 'navigation/repositories', route: '/repositories' },
  { label: 'Workflows', icon: 'navigation/workflows', route: '/workflows' },
  { label: 'Agents', icon: 'navigation/agents', route: '/agents' },
  { label: 'Prompts', icon: 'workspace/graph-history', route: '/prompts' },
  { label: 'Knowledge', icon: 'navigation/knowledge', route: '/knowledge' },
  { label: 'Artifacts', icon: 'navigation/artifacts', route: '/artifacts' },
  { label: 'Approvals', icon: 'navigation/approvals', route: '/approvals' },
  { label: 'Monitoring', icon: 'navigation/monitoring', route: '/monitoring' },
  { label: 'Providers & Models', icon: 'navigation/providers', route: '/providers' },
  { label: 'Settings', icon: 'navigation/settings', route: '/settings' }
];
