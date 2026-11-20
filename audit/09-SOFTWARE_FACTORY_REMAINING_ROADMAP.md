# 09 — Software Factory: Remaining Implementation Roadmap

A prioritized, phased plan to complete the defined product — not to expand it. Phase order respects the
architectural dependencies the source audits identified (notably: security hygiene before anything else;
graph schema + access control before more graph ingestion; graph ingestion + access control before any
graph-powered agent retrieval; sandboxing integration before trusting untrusted task input more broadly).

This is a planning document only. No implementation should begin from this roadmap without the user's
explicit authorization, per the audit brief.

---

## Phase 0 — Security & Configuration Hygiene (immediate, not a development phase)

| Task ID | Feature | Objective |
|---|---|---|
| P0-1 | Rotate placeholder secrets | Replace `SF_JWT_SECRET`/`SF_CREDENTIAL_ENCRYPTION_KEY` with real random values in any non-local `.env`. |
| P0-2 | Disable dev-login outside local dev | Turn off `SF_DEV_QUICK_LOGIN_ENABLED` for any shared/staging/production environment; consider a build-time guard in addition to the runtime flag. |
| P0-3 | Add auth rate limiting | Add basic throttling to `/auth/login` and `/auth/register`. |

- **Current status:** P0-1/P0-2 are live risks today in this environment's `.env` (`06-SECURITY_AND_GOVERNANCE_AUDIT.md` §1, §3). P0-3 is unimplemented.
- **Dependencies:** none.
- **Frontend changes:** none.
- **Backend changes:** config/`.env` only for P0-1/P0-2; add rate-limiting middleware for P0-3.
- **Database changes:** none.
- **Agent infrastructure changes:** none.
- **API changes:** none (P0-3 adds middleware, not new routes).
- **Testing requirements:** a test asserting `/auth/dev-login` 404s when the flag is unset/false (likely already implicitly covered); a rate-limit test for P0-3.
- **Acceptance criteria:** no environment outside local dev has the dev-login bypass reachable; secrets are non-default; repeated failed logins are throttled.

---

## Phase 1 — Already Delivered (context only, nothing to schedule)

Reflects work already in the repository per the source audits: Organizations/Projects/RBAC, Task/Workflow
management, Git worktree + real diff + PR pipeline, the Code Review workspace UI rebuild, Docker Sandbox
isolation, Credential encryption, the thin Neo4j task/workflow graph slice. Not a roadmap item — listed so
the roadmap's starting point is explicit.

---

## Phase 2 — Foundational Gaps That Block Later Phases

| Task ID | Feature | Objective | Current status |
|---|---|---|---|
| P2-1 | Graph Access Service | A dedicated module all Neo4j reads/writes pass through, deriving scope from authenticated identity | NOT IMPLEMENTED |
| P2-2 | Knowledge graph schema | Constraints/indexes for existing + near-term node labels | NOT IMPLEMENTED |
| P2-3 | Sandbox all local-CLI adapters | Route Claude Code/Codex/Gemini CLI/Qwen executions through the existing Docker isolation primitive | PARTIALLY IMPLEMENTED (Docker Sandbox adapter only) |
| P2-4 | Agent Registry foundation | Minimal Agent entity (id/version/capabilities/status) to replace the current single-FK "connection" model | NOT IMPLEMENTED |

- **Dependencies:** P2-1 and P2-2 should land before Phase 3's Git-integration ingestion work (P3-2) to avoid widening an ungated surface. P2-4 is a prerequisite for Phase 5's handoff work but independent of P2-1/P2-2/P2-3.
- **Frontend changes:** none required for P2-1/P2-2/P2-3; P2-4 may need a minimal agent-list view later but not in this phase.
- **Backend changes:** new `graph_access.py` module (P2-1); Neo4j constraint/index migration script (P2-2); adapter dispatch changes to route through `DockerSandboxAdapter`-style execution for local CLIs (P2-3); new `Agent`/`AgentVersion` model (P2-4, additive — does not need to replace `CodingAgentConnection` yet, can coexist).
- **Database changes:** Neo4j schema only for P2-2; new Postgres table(s) for P2-4.
- **Agent infrastructure changes:** P2-3 is the main one — changes how local-CLI adapters are invoked.
- **API changes:** none required for P2-1/P2-2; P2-3 is transparent to the API; P2-4 may add a read-only `/agents` listing route.
- **Testing requirements:** cross-tenant graph-access denial test (P2-1); schema-creation idempotency test (P2-2); a test proving a local-CLI task run is now sandboxed equivalently to Docker Sandbox (P2-3, e.g. network-isolation assertion).
- **Acceptance criteria:** no caller can read/write graph data without going through the access service; Neo4j has real constraints/indexes; every coding-agent runtime (not just `docker_sandbox`) runs with network/resource isolation; a minimal Agent entity exists and is populated for at least the existing six adapters.

---

## Phase 3 — Core Product-Vision Gaps (Coding Workspace Depth)

| Task ID | Feature | Objective | Current status |
|---|---|---|---|
| P3-1 | Test execution | Real test-runner integration, surfaced in the existing "Test Results" UI slot | NOT IMPLEMENTED |
| P3-2 | Repository KG ↔ Git integration | Wire graph ingestion to real `RepositoryConnection`/worktree, record commit SHA | NOT IMPLEMENTED |
| P3-3 | Repository KG extraction breadth | Add imports/dependencies/test-mapping relationships via a parser-adapter framework | NOT IMPLEMENTED (file/top-level-symbol only today) |
| P3-4 | Multi-turn conversation | A `TaskMessage` model + route + UI wiring for follow-up instructions | NOT IMPLEMENTED |
| P3-5 | Review comments | A `ReviewComment` model + CRUD routes + UI wiring (diff viewer already has per-line structure to anchor to) | NOT IMPLEMENTED |
| P3-6 | Planning & Approval gate | A `Plan` entity and an `Approval` model/route; replace the mocked frontend Approvals screen with real data | NOT IMPLEMENTED (backend) / MOCKED (frontend) |

- **Dependencies:** P3-2 depends on P2-1/P2-2 (Phase 2). P3-3 depends on P3-2. P3-4 depends on some session-resume capability per adapter (see Phase 4, but a simpler "append to prompt and re-run" version can ship without full session resume — note this explicitly as a scoped-down interim approach if full resume isn't ready). P3-1 should reuse the sandboxing pattern from P2-3.
- **Frontend changes:** P3-1 wires the existing "Not configured" slot to real data; P3-4 enables the currently-`disabled` composer; P3-5 adds comment UI anchored to diff lines; P3-6 replaces `MockDataService` usage in `approvals.component.ts` with real API calls.
- **Backend changes:** new models (`TestResult`, `ReviewComment`, `Plan`, `Approval`, possibly `TaskMessage`); new routes under `tasks.py` or new route files; test-runner invocation logic in/near `task_execution.py`.
- **Database changes:** new tables for each new model above; Alembic migrations.
- **Agent infrastructure changes:** P3-3 needs the parser-adapter abstraction from the KG audit's proposed sequence; P3-1 needs sandboxed command execution (reuse P2-3).
- **API changes:** new endpoints for messages, comments, plans, approvals, test results.
- **Testing requirements:** each new model needs CRUD + RBAC tests following the existing test-suite conventions (honest-failure, cross-org rejection); P3-2 needs a test proving ingestion now reads the connected repo, not an arbitrary path.
- **Acceptance criteria:** Test Results tab shows real pass/fail data for at least one language; graph ingestion runs against a connected repo's worktree and records a commit SHA; a follow-up message can be sent and visibly affects the next run; a reviewer can leave and see a comment on a diff line; a task can be gated behind an approval before executing.

---

## Phase 4 — RAG / Document Knowledge (contingent on an architecture decision)

| Task ID | Feature | Objective | Current status |
|---|---|---|---|
| P4-1 | Resolve the search-mix design question | Explicitly decide graph vs. keyword vs. vector retrieval mix (currently an open question in the Decision Log) | UNDECIDED |
| P4-2 | Document ingestion + chunking | Build the ingestion/chunking pipeline for the format(s) decided in P4-1 | NOT IMPLEMENTED |
| P4-3 | Embedding + vector storage | Likely pgvector, given the existing PostgreSQL dependency | NOT IMPLEMENTED |
| P4-4 | Retrieval + RAG pipeline | Wire retrieval into `task_execution.py`'s prompt construction | NOT IMPLEMENTED |

- **Dependencies:** P4-1 must happen before P4-2–P4-4 are scheduled with real confidence — building a vector pipeline before the team has decided how it coexists with the Knowledge Graph risks duplicated or conflicting retrieval paths.
- **Frontend changes:** wire the currently-mocked `knowledge-graph.component.ts`/`repository-intelligence.component.ts` to real data once a real backend exists (today they are 100% `MockDataService`).
- **Backend changes:** new ingestion/embedding/retrieval services; new dependency on an embedding provider.
- **Database changes:** `pgvector` extension + embedding columns/tables (if that's the P4-1 decision).
- **Agent infrastructure changes:** a retrieval-injection step before an agent's prompt is sent.
- **API changes:** new ingestion/search endpoints.
- **Testing requirements:** retrieval-relevance tests, citation-correctness tests.
- **Acceptance criteria:** a document can be ingested, embedded, retrieved by a relevant query, and cited.

---

## Phase 5 — Multi-Agent Orchestration & Graph-Powered Retrieval

| Task ID | Feature | Objective | Current status |
|---|---|---|---|
| P5-1 | Agent orchestration layer | Supervisor/Planner, shared workflow state, task contracts, assignment ranking/escalation | NOT IMPLEMENTED |
| P5-2 | Agent replacement / handoff | Session-ID persistence, versioned handover packages, true resume (not restart) | NOT IMPLEMENTED |
| P5-3 | Provider routing & fallback | Multi-provider candidate selection with policy-controlled fallback | NOT IMPLEMENTED |
| P5-4 | Graph-powered agent retrieval | A bounded, scoped, snapshot-pinned graph-retrieval tool callable during execution | NOT IMPLEMENTED |

- **Dependencies:** this is the most dependency-heavy phase. P5-1 depends on P2-4 (Agent Registry foundation). P5-2 depends on P5-1 existing in some form, plus P3-1/P3-5 (test results, review comments) existing to have anything structured to hand over. P5-4 has a **hard dependency** on Phase 2 (P2-1/P2-2) and Phase 3 (P3-2/P3-3) landing first — the Repository KG audit explicitly warns against building agent retrieval on an unvalidated, disconnected, or empty graph. Do not schedule P5-4 ahead of P3-2/P3-3.
- **Frontend changes:** UI to show agent assignment/handoff state; minimal multi-agent visualization if the product wants it surfaced (optional, not required for the backend capability).
- **Backend changes:** the orchestration layer itself (significant new subsystem); session-ID threading through every adapter; a tool-call mechanism in the agent runtime interface for P5-4.
- **Database changes:** workflow-state/task-contract tables; handover-package tables.
- **Agent infrastructure changes:** this phase *is* the agent infrastructure change.
- **API changes:** new orchestration-level endpoints.
- **Testing requirements:** multi-agent collaboration tests; handoff-resumability tests; graph-retrieval relevance/scoping tests.
- **Acceptance criteria:** a task can be decomposed and assigned without a human manually picking the single connection; a task can be handed from one execution to a resumed one without starting over; an agent's retrieved graph context is demonstrably scoped and current.

---

## Phase 6 — Remaining Core-Platform Gaps (can run in parallel with Phases 2–5)

| Task ID | Feature | Objective | Current status |
|---|---|---|---|
| P6-1 | Notifications | Backend model + delivery (reuse the `presence.py` WebSocket pattern or email) | NOT IMPLEMENTED |
| P6-2 | Audit log viewer | A frontend surface for the already-real `AuditLog` backend data | NOT IMPLEMENTED (frontend); BACKEND ONLY today |
| P6-3 | Cost tracking & execution tracing | Parse and store provider usage fields already returned by APIs; structured trace/span model | NOT IMPLEMENTED |
| P6-4 | Prompt injection / output safety | Output-scanning step before task output is persisted/displayed | NOT IMPLEMENTED |

- **Dependencies:** all independent of other phases; can be scheduled opportunistically.
- **Frontend changes:** P6-2 needs a new feature view.
- **Backend changes:** new `Notification` model (P6-1); new read endpoint for audit logs (P6-2, the data already exists); usage-field parsing in each adapter (P6-3); an output-scanning function in the `task_execution.py` completion path (P6-4).
- **Database changes:** new table for P6-1; none for P6-2 (table exists); possibly a `usage` JSON column for P6-3.
- **Agent infrastructure changes:** none beyond P6-3's parsing.
- **API changes:** new routes for P6-1/P6-2.
- **Testing requirements:** standard CRUD/RBAC tests for new models.
- **Acceptance criteria:** a user can see notifications and audit history in the UI; token/cost usage is visible per task; obviously unsafe output patterns are flagged.

---

## Sequencing Summary

```
Phase 0 (security hygiene)  ──────────────────────────────────▶ always first, no dependencies
Phase 2 (graph access + schema, sandbox-everywhere, agent registry foundation)
    │
    ├──▶ Phase 3 (test exec, KG↔Git wiring, KG breadth, multi-turn, review comments, approvals)
    │        │
    │        └──▶ Phase 5 P5-4 (graph-powered retrieval) — hard-gated on Phase 3's KG work
    │
    ├──▶ Phase 5 P5-1/P5-2/P5-3 (orchestration, handoff, routing) — gated on Phase 2 P2-4
    │
    └──▶ Phase 4 (RAG) — gated only on an explicit architecture decision (P4-1), otherwise parallel

Phase 6 (notifications, audit UI, cost tracking, output safety) — fully parallel to all of the above
```

No implementation begins from this roadmap without explicit user authorization.
