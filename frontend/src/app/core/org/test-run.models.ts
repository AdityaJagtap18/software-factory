export type TestFramework = 'pytest' | 'npm' | 'none';

export interface ApiTestRun {
  id: string;
  project_id: string;
  task_id: string;
  framework: TestFramework;
  ran: boolean;
  passed: number;
  failed: number;
  total: number;
  output: string;
  error: string;
  created_at: string;
}
