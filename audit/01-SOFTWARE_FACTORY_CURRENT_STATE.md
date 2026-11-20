# 01 — Software Factory: Current State Overview

Synthesis of all six source audits (`02` through `07`) plus the two scratch fragments produced during this
audit. This document does not introduce new findings — every claim below is attributable to one of those
source documents, which should be read for full evidence trails. Status vocabulary used throughout:
IMPLEMENTED AND VERIFIED / IMPLEMENTED BUT NOT VERIFIED / PARTIALLY IMPLEMENTED / FRONTEND ONLY / BACKEND
ONLY / MOCKED-HARDCODED / NOT IMPLEMENTED / BLOCKED.

No application code was modified to produce this or any audit document.

---

## A. Core Platform

*(Full evidence: deleted scratch fragment, merged below — originally `_fragment-core-platform.md`, backed
by `07-TESTING_AND_VERIFICATION_REPORT.md`'s real pytest run.)*

| Feature | Status | Notes |
|---|---|---|
| Organizations | IMPLEMENTED AND VERIFIED | Real model, routes, RBAC enforcement; 3 passing tests exercise admin/invite/demotion rules. |
| Multi-user workspaces / Projects | IMPLEMENTED AND VERIFIED | Cross-tenant isolation and role enforcement both test-verified. |
| User management | PARTIALLY IMPLEMENTED | Real register/me/org-invite flow; no platform-wide admin user console. |
| Authentication | IMPLEMENTED AND VERIFIED | Real bcrypt+JWT+rotating-refresh. **Operational flag:** a dev-only passwordless `/auth/dev-login` endpoint is **currently enabled** in this environment's `.env` — see `06`. |
| Role-based permissions | IMPLEMENTED AND VERIFIED (coarse-grained) | Org/Project 2–3 tier roles only; no fine-grained ACLs. |
| Task management | IMPLEMENTED AND VERIFIED | 16 passing tests cover RBAC, honest-failure, real execution, cross-org rejection, cancel, SSE, full Git/PR lifecycle. |
| Workflow management (multi-step tasks) | IMPLEMENTED AND VERIFIED | 10 passing tests; sequential steps, fail-stops-remaining, cascade delete. |
| Collaboration / presence | IMPLEMENTED AND VERIFIED (single-process only) | Real WebSocket presence; explicitly does not coordinate across replicas (by its own docstring). |
| Notifications | NOT IMPLEMENTED | No backend model/route/service; frontend bell icon is decorative. |
| Approvals | NOT IMPLEMENTED (backend) / MOCKED-HARDCODED (frontend) | No backend concept of an approval exists at all. Frontend approvals screen reads a hardcoded fake decision list from `MockDataService`. |
| Audit logging | PARTIALLY IMPLEMENTED (BACKEND ONLY) | Real `AuditLog` table, written from 7 route modules; coverage of every sensitive mutation not fully traced; no frontend viewer exists. |
| Dashboard / cross-project aggregation | IMPLEMENTED AND VERIFIED | Correctly scoped to the requesting user's real visible projects; genuinely empty when appropriate. |

---

## B. Agent Management

*(Full evidence and per-feature file/line citations: `03-AGENT_ORCHESTRATION_AUDIT.md`, section B.)*

**Headline finding: no agent-orchestration layer exists.** The product vision (per the Architecture
Decision Log) describes a Supervisor/Planner/specialized-Agent-Worker system with an Agent Registry,
controlled agent communication, hybrid task decomposition, and policy-based assignment. None of this is
implemented. What exists instead is a single-adapter, single-prompt task runner.

| Feature | Status |
|---|---|
| Agent registration / configuration | PARTIALLY IMPLEMENTED (modeled as a provider "connection," not an agent) |
| Agent roles / capability schema | MOCKED-HARDCODED (flat per-adapter label list, no role taxonomy) |
| Agent assignment | IMPLEMENTED BUT NOT VERIFIED (trivial single FK; no registry, ranking, or escalation) |
| Agent execution | IMPLEMENTED AND VERIFIED (for the single-prompt case) |
| Agent communication / collaboration | NOT IMPLEMENTED |
| Agent lifecycle / monitoring | PARTIALLY IMPLEMENTED (4-state status only; no trace/telemetry store) |
| Agent failure handling | IMPLEMENTED AND VERIFIED (fail-honest; no retry/escalation policy) |
| Agent replacement / handoff | NOT IMPLEMENTED (zero code references; "restart" = fresh stateless run, not resume) |
| Agent session persistence | NOT IMPLEMENTED (no session ID ever threaded to any adapter) |

---

## C. Provider Integrations

*(Full evidence: `03-AGENT_ORCHESTRATION_AUDIT.md`, section C.)*

| Feature | Status |
|---|---|
| Common Agent Runtime Interface | IMPLEMENTED AND VERIFIED — but only one adapter family, not the two (LLM vs. coding-agent) the architecture calls for |
| Provider executability (Claude Code, Codex, Gemini CLI, Qwen, Docker Sandbox, Custom) | IMPLEMENTED AND VERIFIED — all 6 adapters genuinely shell out to real CLIs or make real HTTPS calls, nothing fabricated. Whether the specific binaries/daemons are installed on any given host is environment-dependent and was not independently confirmed for this host. |
| Model configuration / version pinning policy | MOCKED-HARDCODED (model names are Python literals inside each adapter function; no override mechanism) |
| Credential management | IMPLEMENTED AND VERIFIED (Fernet-encrypted at rest, decrypted only at point of use) |
| Provider routing / fallback | NOT IMPLEMENTED (exactly one connection per org+runtime; no multi-provider selection logic) |
| Provider health monitoring | IMPLEMENTED AND VERIFIED (synchronous, on-demand only — no background monitoring loop) |
| Cost tracking | NOT IMPLEMENTED |
| Execution tracing | NOT IMPLEMENTED |

---

## D. Coding Agent Workspace

*(Full evidence and line-level citations: originally `_fragment-coding-workspace.md`, merged below. See
also `03-AGENT_ORCHESTRATION_AUDIT.md` for the adapter-level backing.)*

This is the most mature part of the product for the **happy path**: natural-language task → real git
worktree → real file edits → real diff → real PR. It stops well short of a full "autonomous coding agent
platform" everywhere beyond that path.

| Feature | Status |
|---|---|
| Natural-language task submission | IMPLEMENTED AND VERIFIED |
| Repository context loading | PARTIALLY IMPLEMENTED (real shallow clone only; no indexing/curation before execution) |
| Codebase inspection | PARTIALLY IMPLEMENTED (delegated entirely to whatever the underlying CLI does on its own) |
| Implementation planning | NOT IMPLEMENTED (no plan entity, no approval-before-execution step) |
| Actual file modifications | IMPLEMENTED AND VERIFIED (local-CLI + connected-repo path only) |
| Terminal execution | PARTIALLY IMPLEMENTED (opaque — inside the CLI's own subprocess, no platform-level tool surface) |
| Follow-up instructions / multi-turn conversation | NOT IMPLEMENTED — UI composer is `disabled`, with the explicit on-screen text: *"Follow-up conversation isn't available yet — each task currently runs its description as a single instruction."* |
| Persistent execution state / session resume | NOT IMPLEMENTED |
| Checkpoints | NOT IMPLEMENTED (only a post-hoc git commit after the run finishes) |
| Cancellation | IMPLEMENTED AND VERIFIED (real DB-polled flag, real subprocess termination) |
| Recovery | PARTIALLY IMPLEMENTED ("Restart" = brand-new worktree + brand-new run, not resume-from-checkpoint) |
| Git worktrees / branch creation | IMPLEMENTED AND VERIFIED |
| Git diff generation (backend + frontend parsing) | IMPLEMENTED AND VERIFIED — this is the recently-rebuilt real diff viewer; both the backend's real `git diff` capture and the frontend's unified-diff parser (`diff-parser.ts`) are genuine, not mocked |
| File-level code review (viewing) | FRONTEND ONLY — browsing/viewing works; no commenting capability exists |
| Review comments | NOT IMPLEMENTED — explicit on-screen text: *"Review comments aren't supported yet — there's no backend model for them."* |
| Test execution | NOT IMPLEMENTED — explicit on-screen text: *"Not configured — no test runner is integrated yet."* |
| Quality / security scanning | NOT IMPLEMENTED — explicit on-screen text: *"Not configured — no quality or security scanner is integrated yet."* |
| Pull request creation | IMPLEMENTED AND VERIFIED — real GitHub PR, conditional on an actual file change and a connected repo; degrades gracefully (never fakes success) if push/PR fails |
| Artifacts tab | NOT IMPLEMENTED — explicit on-screen text: *"...will appear here once the artifact store is connected."* |
| Execution Logs tab | IMPLEMENTED BUT MINIMAL — shows real raw adapter output, but as an unstructured text blob, not a structured multi-stream log |

**On the recent Task Center / Code Review rebuild specifically:** the latest UI change (committed as
`409265c` in this repository's history) restructured the task workspace into the breadcrumb/header/tabs/
3-column layout matching the supplied reference, and is consistent in its own on-screen copy with every
finding above — every unbuilt capability (tests, quality/security, review comments, multi-turn chat,
artifacts) is shown as an honest "not configured" empty state rather than fabricated data. This audit found
no discrepancy between what that UI claims and what the backend actually does.

---

## Knowledge Graph & Repository Intelligence (summary — full detail in `04`)

Neo4j is genuinely integrated (real driver, real Cypher, real connection), but only as a thin slice: node
labels are limited to `Project, User, Connection, Workflow, Task, File, Class, Function`, and relationships
mirror Postgres entities plus one real-but-shallow `File -[:DEFINES]-> Class/Function` edge. Verified live:
the project's own Neo4j instance currently holds **0 nodes**. Critically:

- Ingestion only reads an arbitrary **local filesystem path**, not a connected Git repository — there is no
  code path linking `RepositoryConnection`/`git_sync.py` to graph ingestion.
- No import/dependency/call-graph/test-mapping relationships exist (`CALLS`, `DEPENDS_ON`, `TESTS`,
  `MODIFIES` are all absent).
- No incremental updates, no commit-level snapshots, no schema (constraints/indexes).
- **No coding agent ever queries the graph during execution** — agents get a bare prompt plus (optionally)
  a raw worktree checkout. There is no graph-powered or RAG-powered retrieval initiated by this platform.
- No dedicated Graph Access Service exists; isolation today is ordinary Postgres/API-layer project
  membership plus an unenforced convention inside the one graph service module.

See `04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` for full evidence and a proposed, dependency-ordered
implementation sequence.

## RAG & Knowledge Management (summary — full detail in `05`)

**No RAG or document-knowledge system exists anywhere in this codebase.** No ingestion, chunking,
embedding, vector storage, semantic search, or retrieve-then-generate pipeline exists in any form —
confirmed by dependency inspection (`requirements.txt` has no vector/embedding/OCR/langchain packages),
schema inspection (no document/embedding/vector table in any of 11 Alembic migrations), and code inspection
(the only "knowledge" backend code is the Neo4j graph feature above, which indexes code symbols, not
documents or free text). The frontend's "Knowledge" feature and two UI strings mentioning "RAG" are
cosmetic mock data with no backing logic. See `05-RAG_AND_KNOWLEDGE_AUDIT.md`.

---

## Security, Governance & Testing (summary — full detail in `06`, `07`)

- Core auth/RBAC/multi-tenant-isolation skeleton is real and test-verified (112 passed / 4 honest
  environment-gated skips / 0 failed, backend pytest suite; frontend `tsc --noEmit` clean).
- Production blockers found: a passwordless dev-login endpoint **currently enabled** in this environment's
  `.env`; JWT secret and credential-encryption key still at their insecure placeholder defaults; no rate
  limiting anywhere; no sandboxing for any coding-agent runtime except the dedicated Docker Sandbox adapter
  (the four LLM-CLI runtimes execute directly on the backend host); no prompt-injection protection; no real
  human-approval gate (only a mocked frontend screen).
- Docker Sandbox isolation is real and verified live (network isolation and cancellation-kills-container
  both proven by running the test suite against the real Docker daemon).

---

## Overall A–D status matrix (quick reference)

| Area | Dominant status |
|---|---|
| A. Core Platform | Mostly IMPLEMENTED AND VERIFIED, with Notifications/Approvals NOT IMPLEMENTED/MOCKED |
| B. Agent Management | Mostly NOT IMPLEMENTED / PARTIALLY IMPLEMENTED — no orchestration layer exists |
| C. Provider Integrations | Core adapter execution IMPLEMENTED AND VERIFIED; routing/fallback/cost/tracing NOT IMPLEMENTED |
| D. Coding Agent Workspace | Happy-path (submit → edit → diff → PR) IMPLEMENTED AND VERIFIED; everything else (multi-turn, tests, quality, review comments, artifacts) NOT IMPLEMENTED with honest empty states |
| Knowledge Graph | PARTIALLY IMPLEMENTED — real but shallow, disconnected from Git, not agent-accessible |
| RAG / Knowledge Management | NOT IMPLEMENTED — does not exist in any form |
| Security / Governance | Core skeleton IMPLEMENTED AND VERIFIED; several concrete production blockers currently live |
| Testing | Real test suite, real evidence; 112/116 passed, 4 honest skips, 0 failures |
