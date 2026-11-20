# 08 — Implementation Gap Analysis

Synthesis of `02`–`07`. For every capability, the table states: original requirement (as the source audits
cite it from the Architecture Decision Log / docs), current implementation, evidence, remaining work,
dependencies, priority, and suggested phase. Findings are not softened relative to the source audits.

Priority legend: **P0** = production blocker / currently-live risk. **P1** = core product-vision gap,
blocks the next major capability. **P2** = material gap, not blocking. **P3** = nice-to-have / deferrable.

---

## 1. Agent Orchestration

| | |
|---|---|
| **Requirement** | Supervisor + Planner + specialized Agent Workers, Agent Registry (ID/version/capabilities/status), controlled agent communication via shared workflow state + task contracts, hybrid task decomposition/assignment, policy-controlled provider routing/fallback (Decision Log §362–944). |
| **Current implementation** | A single-adapter, single-prompt task runner. `Task.coding_agent_connection_id` is a plain FK to one `CodingAgentConnection`; no registry, no roles, no shared state, no task contracts. |
| **Evidence** | `backend/app/models/agent_runtime.py`; `backend/app/services/task_execution.py:60-99`; zero grep hits for "registry"/"supervisor"/"task contract" in `backend/app`. See `03-AGENT_ORCHESTRATION_AUDIT.md` §B1–B6. |
| **Remaining work** | Build Agent Registry entity; Supervisor/Planner decomposition; shared workflow-state model; task-contract schema; assignment ranking + escalation. |
| **Dependencies** | None blocking — this is foundational; most other agent-level work (handoff, multi-agent collaboration) depends on this existing first. |
| **Priority** | **P1** |
| **Suggested phase** | Phase 2 (after security hardening, before handoff/collaboration). |

## 2. Agent Replacement / Handoff

| | |
|---|---|
| **Requirement** | A replacement agent can receive original instruction, approved plan, repo state/branch/diff, completed/remaining steps, execution logs, test results, review comments — a resumable handoff, not a restart (Decision Log, Decision 3 §1227–1240). |
| **Current implementation** | NOT IMPLEMENTED. Zero code references to handoff/replace/reassign. "Restart" deletes the worktree and re-runs the same prompt from scratch — a stateless new execution, not a resume. |
| **Evidence** | `03-AGENT_ORCHESTRATION_AUDIT.md` §B8 (full citation list); `git_worktree.py:108-111` (worktree deleted and recreated on restart). |
| **Remaining work** | Session-ID persistence on `Task`/`CodingAgentConnection`; a plan/approval entity to hand over; structured execution-log and test-result models; a "handoff" API + UI action distinct from "restart." |
| **Dependencies** | Depends on Agent Orchestration (#1) existing in some form, and on Test Execution (#9) / Review Comments (#10) existing to have anything structured to hand over. |
| **Priority** | **P2** |
| **Suggested phase** | Phase 3 (after orchestration and test/quality integration exist). |

## 3. Provider Routing, Fallback, Cost Tracking, Execution Tracing

| | |
|---|---|
| **Requirement** | Policy-controlled provider routing/fallback, model version pinning as a deliberate control, cost tracking, execution tracing (Decision Log §886–944, §1365–1389). |
| **Current implementation** | NOT IMPLEMENTED for all four. Model names are hardcoded Python literals per adapter; exactly one connection per org+runtime; no retry/fallback; zero cost/trace instrumentation anywhere. |
| **Evidence** | `03-AGENT_ORCHESTRATION_AUDIT.md` §C4, C6, C8, C9 — each confirmed by whole-codebase grep returning zero matches. |
| **Remaining work** | Per-task/per-connection model selection; multi-provider candidate list + fallback policy; token/cost accounting (minimum: parse and store usage fields already returned by provider APIs); structured execution trace/span model. |
| **Dependencies** | None blocking; independent of orchestration/handoff work. |
| **Priority** | **P2** (cost tracking/tracing), **P3** (routing/fallback — only matters once multiple providers are actually used concurrently) |
| **Suggested phase** | Phase 2–3, can run in parallel with other backend work. |

## 4. Multi-turn Conversation / Follow-up Instructions

| | |
|---|---|
| **Requirement** | Persistent, multi-turn task conversation (per the pasted product spec). |
| **Current implementation** | NOT IMPLEMENTED. UI composer is `disabled` with an explicit admission; no message/turn model or route exists; every execution is one prompt in, one result out. |
| **Evidence** | `task-workspace.component.html:109-113` (quoted verbatim in `01`); `backend/app/api/routes/tasks.py` has no message/turn routes. |
| **Remaining work** | A `TaskMessage`/turn model; a route to append a follow-up instruction and re-invoke the adapter with accumulated context (requires session-resume support per adapter, see #2); UI composer wiring. |
| **Dependencies** | Session persistence (part of #2) is a prerequisite for this to be a real conversation rather than independent re-runs. |
| **Priority** | **P1** |
| **Suggested phase** | Phase 3. |

## 5. Implementation Planning / Approval-before-execution

| | |
|---|---|
| **Requirement** | A planning phase with human approval before an agent executes (implied by "Approvals" in the core-platform spec and by Decision 3's "versioned handover packages" needing a plan artifact). |
| **Current implementation** | NOT IMPLEMENTED anywhere — no `Plan` entity exists; starting a task executes immediately. |
| **Evidence** | `03-AGENT_ORCHESTRATION_AUDIT.md` §B1, B8; `_fragment-coding-workspace.md` D3 (merged into `01`). |
| **Remaining work** | A `Plan` entity + approval-gate route; UI to review/approve a plan before execution begins. |
| **Dependencies** | None blocking technically, but should land alongside Approvals (#11) since they're the same underlying capability. |
| **Priority** | **P2** |
| **Suggested phase** | Phase 3 (pairs naturally with #11). |

## 6. Test Execution

| | |
|---|---|
| **Requirement** | Real test execution as part of a task's run, surfaced in the Code Review workspace's "Test Results" panel. |
| **Current implementation** | NOT IMPLEMENTED — explicit UI text: "Not configured — no test runner is integrated yet." No test-runner invocation exists anywhere in the backend. |
| **Evidence** | `task-workspace.component.html:198-199, 264`; `03-AGENT_ORCHESTRATION_AUDIT.md` confirms no test-runner code in `task_execution.py` or `backend/app/services/`. |
| **Remaining work** | A test-runner integration (language-aware, likely sandboxed via the existing `DockerSandboxAdapter` pattern since that's the only real isolation primitive already built); a `TestResult` model; UI wiring (already has the empty-state slot ready). |
| **Dependencies** | Should reuse the Docker Sandbox isolation pattern (#13) rather than running arbitrary test commands directly on the backend host. |
| **Priority** | **P1** |
| **Suggested phase** | Phase 3. |

## 7. Quality Checks / Security Scanning

| | |
|---|---|
| **Requirement** | Quality and security scanning results surfaced per task, per the Code Review reference UI. |
| **Current implementation** | NOT IMPLEMENTED — explicit UI text: "Not configured — no quality or security scanner is integrated yet." No linter/SAST integration anywhere. |
| **Evidence** | `task-workspace.component.html:203-204, 271`. |
| **Remaining work** | Integrate a linter/SAST tool (sandboxed, same rationale as #6); a `QualityFinding`/`SecurityFinding` model; UI wiring. |
| **Dependencies** | Same sandboxing dependency as #6; can be built alongside it. |
| **Priority** | **P2** |
| **Suggested phase** | Phase 3–4. |

## 8. Review Comments / Reviewer Agent

| | |
|---|---|
| **Requirement** | File/line-level review comments, plus a reviewer-agent persona per the pasted product spec. |
| **Current implementation** | NOT IMPLEMENTED — explicit UI text: "Review comments aren't supported yet — there's no backend model for them." No review-comment model exists. |
| **Evidence** | `task-workspace.component.html:253,256`. |
| **Remaining work** | A `ReviewComment` model (file path, line, author, body, resolved state); CRUD routes; UI wiring (diff viewer already has per-line structure to anchor comments to, per `diff-parser.ts`'s `DiffLine` type). A dedicated reviewer-agent persona depends on Agent Orchestration (#1) existing first. |
| **Dependencies** | Review-comment CRUD is independent and can ship before #1; a *reviewer agent* specifically depends on #1. |
| **Priority** | **P2** (comment model), **P3** (reviewer agent persona) |
| **Suggested phase** | Phase 3 (model/UI), Phase 5+ (reviewer agent). |

## 9. Approvals (Core Platform)

| | |
|---|---|
| **Requirement** | Real human approval gates in the core platform workflow. |
| **Current implementation** | NOT IMPLEMENTED (backend) / MOCKED-HARDCODED (frontend). No backend model/route exists; the frontend approvals screen is built entirely on `MockDataService` with a hardcoded fake decision history. |
| **Evidence** | `06-SECURITY_AND_GOVERNANCE_AUDIT.md` §9; `frontend/src/app/features/approvals/approvals.component.ts:22-27`. |
| **Remaining work** | An `Approval` model + routes; wiring into task/PR lifecycle as an optional or mandatory gate; replace the mocked frontend data with real API calls. |
| **Dependencies** | Pairs with #5 (Planning). |
| **Priority** | **P2** |
| **Suggested phase** | Phase 3. |

## 10. Notifications

| | |
|---|---|
| **Requirement** | Platform notifications (core platform spec). |
| **Current implementation** | NOT IMPLEMENTED. No backend model/route/service. Frontend bell icon is decorative only. |
| **Evidence** | Zero grep matches for "notification" in `backend/app`; `_fragment-core-platform.md` (merged into `01`). |
| **Remaining work** | A `Notification` model, delivery mechanism (poll, WebSocket via the existing `presence.py` pattern, or email), UI wiring. |
| **Dependencies** | None blocking. |
| **Priority** | **P3** |
| **Suggested phase** | Phase 4+. |

## 11. Repository Knowledge Graph — Schema & Depth

| | |
|---|---|
| **Requirement** | Full Repository/Engineering Knowledge Graph: repos, branches, commits, directories, files, classes, functions, methods, symbols, imports, dependencies, API endpoints, DB models/relationships, config, tests, docs, and relationships (`CALLS`, `DEPENDS_ON`, `TESTS`, `MODIFIES`, etc.) with schema constraints/indexes (Decision Log Domain 4, DB-11, DB-12). |
| **Current implementation** | PARTIALLY IMPLEMENTED. Real Neo4j connection; only 8 node labels and 7 relationship types, all mirroring Postgres entities plus one shallow `File-[:DEFINES]->Class/Function` edge. No constraints/indexes exist. Live graph currently has 0 nodes. |
| **Evidence** | `04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` §3.1, §3.2, confirmed live via `cypher-shell`. |
| **Remaining work** | Schema (constraints/indexes) first; then a parser-adapter framework for import/dependency/endpoint/DB-model/test extraction; polyglot language support beyond Python (`ast`) and a single TS/JS regex. |
| **Dependencies** | Should land before #12/#13/#14 per the source audit's own proposed sequence — building richer retrieval on an unconstrained, shallow graph is wasted work. |
| **Priority** | **P1** |
| **Suggested phase** | Phase 2 (schema), Phase 3–4 (extraction breadth). |

## 12. Repository Knowledge Graph — Git Integration

| | |
|---|---|
| **Requirement** | The graph is built from the platform's actual connected Git repositories, updated incrementally on commit, with commit-level snapshots tasks can pin (DB-04 through DB-10). |
| **Current implementation** | NOT IMPLEMENTED. Ingestion only reads an arbitrary local filesystem path supplied directly in the API request body — zero connection to `RepositoryConnection`/`git_sync.py`/webhooks. No incremental updates; every ingestion fully deletes and replaces the subgraph. No snapshot/commit-SHA tracking at all. |
| **Evidence** | `04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` §3.2, §3.3; `knowledge_graph.py` lines 1-5, 230 (explicit code comment admitting this). |
| **Remaining work** | Wire ingestion to the real Git worktree/connection path; record source commit SHA; build the incremental-diff-and-update worker; snapshot/validation/publish model. |
| **Dependencies** | Depends on #11 (schema) landing first; depends on the Git integration (`git_sync.py`, `RepositoryConnection`) already being reliable, which the source audits found to be the case for the happy-path task flow. |
| **Priority** | **P1** |
| **Suggested phase** | Phase 3. |

## 13. Repository Knowledge Graph — Access Control

| | |
|---|---|
| **Requirement** | A dedicated, mandatory Graph Access Service deriving scope from authenticated identity for every graph read/write, per a shared-database-with-enforced-isolation design (Decision Log DB-02). |
| **Current implementation** | NOT IMPLEMENTED. No such module exists. Isolation today is the ordinary Postgres/API-layer `require_project_access` dependency plus an unenforced `project_id`-parameter convention inside `knowledge_graph.py` itself — callers pass scope in, rather than the service deriving it. |
| **Evidence** | `04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` §3.5 (zero grep matches for "graph_access"/"GraphAccessService"). |
| **Remaining work** | Extract a single access-control module all graph operations must pass through; cross-tenant denial tests. |
| **Dependencies** | None blocking technically, but should land **before** #12 adds more ingestion surface, since more write paths increase what's currently unguarded by a dedicated layer. |
| **Priority** | **P0** (it's a real, if currently low-blast-radius, isolation gap in a multi-tenant product) |
| **Suggested phase** | Phase 2 — before further graph ingestion work. |

## 14. Graph-Powered Coding Agent Retrieval

| | |
|---|---|
| **Requirement** | Coding agents query the repository knowledge graph for context (symbol lookup, dependency traversal, impact analysis, test discovery) during execution — "graph-powered coding intelligence" (spec §3.4). |
| **Current implementation** | NOT IMPLEMENTED. `task_execution.py` and every adapter have zero references to `knowledge_graph`/`neo4j`. Agents receive a bare prompt plus, optionally, a raw worktree checkout; whatever "inspection" happens is entirely inside the external CLI tool, not initiated by this platform. No graph, vector, or hybrid retrieval exists at all. |
| **Evidence** | `04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` §3.4 (full grep trail). |
| **Remaining work** | A bounded, scoped, snapshot-pinned graph-retrieval tool the agent runtime can call, routed through the Graph Access Service (#13). |
| **Dependencies** | **Hard dependency** on #11, #12, #13 all landing first — the source audit explicitly warns against building this before the graph has real, validated, snapshot-pinned content, and before agent orchestration (#1) exposes any tool-call mechanism to adapters (which also does not currently exist). |
| **Priority** | **P3** (correctly sequenced last among graph work; do not pull forward) |
| **Suggested phase** | Phase 5+, strictly after Phases 2–4 graph work and after some agent tool-call mechanism exists. |

## 15. RAG / Document Knowledge (entire capability)

| | |
|---|---|
| **Requirement** | Document ingestion, chunking, embedding, vector storage, semantic/hybrid search, reranking, a retrieve-then-generate RAG pipeline, source citations, knowledge versioning (spec §5). |
| **Current implementation** | **NOT IMPLEMENTED in any form whatsoever.** No dependency, no schema, no code path for any sub-capability. This is not a partial build — it is an unbuilt capability area, confirmed by `requirements.txt`, 11 Alembic migrations, and whole-tree grep all returning nothing. The Architecture Decision Log itself lists the graph/keyword/vector search mix as an open, undecided question. |
| **Evidence** | `05-RAG_AND_KNOWLEDGE_AUDIT.md` (full evidence table). |
| **Remaining work** | Everything: choose a vector store (pgvector is the natural fit given the existing PostgreSQL dependency), a document ingestion/chunking pipeline, an embedding provider, a retrieval API, and a RAG-aware prompt-construction step in `task_execution.py`. |
| **Dependencies** | None blocking relative to other phases — this is a fully independent subsystem. It should NOT be built before the architecture question in the Decision Log (graph vs. keyword vs. vector mix) is actually resolved by the team, since building it prematurely risks duplicating or conflicting with the Knowledge Graph work. |
| **Priority** | **P2** — real product-vision gap, but explicitly deferred as an open question by the project's own architecture doc, so it should not be scheduled ahead of resolving that design question. |
| **Suggested phase** | Phase 4+, pending an explicit architecture decision first. |

## 16. Security Defaults Currently Live (not a feature gap — an operational risk)

| | |
|---|---|
| **Requirement** | Secure-by-default configuration; no authentication bypass reachable in any environment that could be mistaken for production; rotated secrets. |
| **Current implementation** | The dev-only `/auth/dev-login` passwordless endpoint is **currently enabled** in this environment's checked `.env` (`SF_DEV_QUICK_LOGIN_ENABLED=true`); `SF_JWT_SECRET` and `SF_CREDENTIAL_ENCRYPTION_KEY` are still their insecure literal placeholder defaults (`dev-secret-change-me`, `dev-credential-key-change-me`). No rate limiting exists on `/auth/login` or `/auth/register`. |
| **Evidence** | `06-SECURITY_AND_GOVERNANCE_AUDIT.md` §1, §3 (direct `.env` read). |
| **Remaining work** | Rotate `SF_JWT_SECRET`/`SF_CREDENTIAL_ENCRYPTION_KEY` to real random values before any non-local use; disable `SF_DEV_QUICK_LOGIN_ENABLED` outside local dev, and consider a build-time (not just runtime) guard; add rate limiting to auth endpoints. |
| **Dependencies** | None — this is independent of all other work and should happen immediately for any environment beyond the developer's own machine. |
| **Priority** | **P0** |
| **Suggested phase** | Immediate / Phase 0 (configuration hygiene, not a development phase). |

## 17. Sandbox Isolation for Non-Docker Runtimes

| | |
|---|---|
| **Requirement** | Consistent, enforced sandbox isolation for every coding-agent execution (Decision Log Decision 3: "Docker isolation per coding execution attempt"). |
| **Current implementation** | PARTIALLY IMPLEMENTED. Real, verified isolation exists only for the dedicated `DockerSandboxAdapter`. The four LLM-CLI runtimes (Claude Code, Codex, Gemini CLI, Qwen) execute directly on the backend host via `subprocess`, with no sandboxing, network restriction, or resource limiting beyond the working directory they're launched in. |
| **Evidence** | `06-SECURITY_AND_GOVERNANCE_AUDIT.md` §5. |
| **Remaining work** | Either route all local-CLI adapters through the same Docker isolation primitive already built, or accept and document the current risk explicitly for any environment where task input isn't fully trusted. |
| **Dependencies** | None — the isolation primitive (Docker) already exists and works; this is an integration task, not new infrastructure. |
| **Priority** | **P1** |
| **Suggested phase** | Phase 2. |

## 18. Prompt Injection / Agent Output Safety

| | |
|---|---|
| **Requirement** | Protection against a malicious/compromised task description directing a coding-agent CLI to do something unsafe within its own tool-permission model. |
| **Current implementation** | NOT IMPLEMENTED. The task description is passed verbatim as the prompt with no sanitization, injection detection, or output scanning. The only existing guardrail (`claude -p --permission-mode acceptEdits` gating Bash) is the underlying CLI's own feature, not something this platform enforces. |
| **Evidence** | `06-SECURITY_AND_GOVERNANCE_AUDIT.md` §4. |
| **Remaining work** | At minimum: an output-scanning step for obvious exfiltration/secret-leak patterns before task output is persisted/displayed; longer-term, a prompt-firewall layer. |
| **Dependencies** | None blocking, but lower urgency than #16/#17 since it requires untrusted task input to be a realistic threat model in the deployment in question. |
| **Priority** | **P2** |
| **Suggested phase** | Phase 2–3. |
