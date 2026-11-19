# Decisions and Gaps (Stage 0)

## Decisions made this session

- **Scope**: UI shell only, single session. User explicitly chose this over a
  thin full-stack vertical slice or infra-first scaffold.
- **No backend stub**: rather than build a partial FastAPI skeleton that
  cannot do anything real yet, mock data lives in Angular services so the
  contract (TypeScript interfaces) is ready to be swapped for real HTTP calls
  later without changing component code.
- **Routing structure**: one route per reference page under a shared app-shell
  layout, matching the sidebar nav in the Dashboard reference image (Dashboard,
  Projects, Repositories, Workflows, Agents, Knowledge, Artifacts, Approvals,
  Monitoring, Admin/Settings) plus the Login route outside the shell, plus the
  additional screens from the full 14-page list (Project Workspace, Task
  Workspace, Code Changes & Review, Provider & Model Management, Prompt
  Registry) nested under Projects/Settings as appropriate.

## Gaps vs. the master prompt (explicit, not silent)

- Coding Agent Connections wizard, Local Agent Bridge, Credential Broker: not
  built. These require real runtime detection and secrets infrastructure that
  don't exist yet.
- No multi-tenant backend, no RLS, no real auth.
- No Neo4j/graph backend — Knowledge Graph Explorer and Repository
  Intelligence pages render with mock graph data for layout purposes only.
- No Temporal/LangGraph — Workflow Visualizer shows mock workflow state.

These gaps are intentional and match the user's chosen scope for this pass,
not an oversight.
