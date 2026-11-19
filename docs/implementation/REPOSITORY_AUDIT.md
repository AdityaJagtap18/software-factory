# Repository Audit (Stage 0)

Date: 2026-11-19

## What existed before this session

- `UI reference/` — 14 PNG mockups covering all pages named in the master prompt
  (Dashboard, Login, Project Workspace, Workflow, Agent Command Center, Knowledge
  Graph, Repository Intelligence, Task Workspace, Code Changes & Review,
  Approval Center, Monitoring & Observability, Provider & Model Management,
  Prompt Registry, Settings).
- `# Software Factory.txt` — original architecture specification (added by user
  this session).
- `Software_Factory_Architecture_Decision_Log (1).md` — finalized architecture
  decisions, domains 1–8 (added by user this session).
- `Software_Factory_SVG_Assets.zip` — icon/logo pack (added by user this
  session), extracted to `svg-assets-extracted/` then copied into the Angular
  app's asset folder.
- No source code, no git repository, no infrastructure, no backend.

## What this session is scoped to build

Per explicit user decision, this is a **single-session, single-agent** effort,
not the multi-month team build the master prompt describes. The user chose:

1. Add the missing architecture docs/SVG pack (done).
2. Start with an **Angular UI shell** recreating the 14 reference screens as a
   real, routed Angular application with components and mock data — no backend
   yet.
3. Tooling: Node 26.13, npm 11.20, Angular CLI 22.3, Python 3.13.5, Git 2.51 are
   all present; no installs were required.

Everything in the master prompt describing FastAPI, LangGraph, Temporal,
PostgreSQL, Neo4j, Docker execution, real Codex/Claude Code runtime
integrations, the Local Agent Bridge, and the Credential Broker is **not**
implemented in this pass. Those require infrastructure (databases, containers,
secrets management, real coding-agent CLIs installed and authenticated) and
scope well beyond one UI-focused session. They remain the Phase 1+ backend
work described in `IMPLEMENTATION_PLAN.md`.

## Decision: UI shell first, backend later

This follows the architecture decision log's own "first implementation slice"
recommendation (§11.1), item 4: "Angular application shell with authentication,
organization/project selection and a basic project workspace," without waiting
for the full backend slice — the user explicitly deferred the rest.
