# Implementation State — Ground Truth

Last updated: 2026-11-21, after the Phase 5 (P5-1/P5-2/P5-3) commit `2b70be9`. Update this file at the end of every
milestone; it is the fast answer to "is X done" — check here before re-reading audit docs or
re-grepping the codebase for status.

## Phase status at a glance

| Phase | Status |
|---|---|
| Phase 0 — Security & Configuration Hygiene | **DONE** (commit `89a9f51`) |
| Phase 1 — Already Delivered (the pre-audit baseline itself) | DONE (nothing to schedule — context only) |
| Phase 2 — Foundational Gaps | **DONE**, P2-3 intentionally partial (commit `c20000c`) |
| Phase 3 — Core Product-Vision Gaps (Coding Workspace Depth) | **DONE** (commit `6f21376`, then P3-3/P3-4 commit `7d0071a`) |
| Phase 4 — RAG / Document Knowledge | **DONE** (P4-1..P4-4, see below) |
| Phase 5 — Multi-Agent Orchestration & Graph-Powered Retrieval | **PARTIAL** — P5-1/P5-2/P5-3 **DONE** (commit `2b70be9`), P5-4 (B4 graph-powered retrieval) **NOT STARTED** (see below) |
| Phase 6 — Remaining Core-Platform Gaps | NOT STARTED |

## Environment note for whoever runs tests next

The committed branch (as of `98b73ce`) does not boot on a clean checkout: `backend/app/main.py`
imported a `repository_intelligence` route module that was never committed (it only exists as
pre-existing *uncommitted* work in the separate main checkout — see the section below). Fixed by
removing that import/`include_router` call from `main.py` in this pass; the uncommitted
`repository_intelligence.py` itself was not touched. If/when that module is actually committed,
re-add the import.

Also: the shared Postgres test database (`software_factory_test` on `localhost:5433`) already has
a `tasks.knowledge_context NOT NULL` column applied directly against it by the main checkout's
*uncommitted* migration — this clean worktree's `Task` model doesn't define that column, so any
test that inserts a `Task` fails with a `NotNullViolation` against that shared DB. Worked around for
this pass by pointing `SF_TEST_DATABASE_URL` at a separate local database
(`postgresql+psycopg2://sf:sf@localhost:5433/sf_worktree_p3`) instead of the shared one. Do the same
in any worktree whose Postgres schema doesn't match the shared test DB's current (possibly
uncommitted-migration-contaminated) state.

## Phase 0 — DONE (commit `89a9f51`)

| ID | Item | Proof |
|---|---|---|
| P0-1 | Rotate placeholder secrets | `app/core/config.py::_validate_non_local_settings` fails fast on non-local placeholder secrets. `tests/test_config_security.py` |
| P0-2 | Disable dev-login outside local dev | `app/api/routes/auth.py::_dev_login_permitted` requires `settings.is_local_dev`. `tests/test_auth.py::test_dev_login_404_when_disabled` |
| P0-3 | Auth rate limiting | `app/core/rate_limit.py`. `tests/test_auth.py::test_login_rate_limited_after_repeated_attempts`, `test_register_rate_limited_after_repeated_attempts` |

## Phase 2 — DONE (commit `c20000c`)

| ID | Item | Proof |
|---|---|---|
| P2-1 | Graph Access Service | `app/services/graph_access.py`. `tests/test_graph_access.py` |
| P2-2 | Knowledge graph schema (constraints/indexes) | `knowledge_graph.ensure_schema()` extended; called at startup via lifespan in `main.py` |
| P2-3 | Sandbox all local-CLI adapters | **PARTIAL by design** — plumbing built and Docker-verified (`tests/test_cli_sandboxing.py`), but off by default (`SF_*_SANDBOX_IMAGE` all empty — no real per-CLI Docker image exists yet). Zero behavior change today. |
| P2-4 | Agent Registry foundation | `app/models/agent.py`, `app/services/agent_registry.py`, `GET /agents`. `tests/test_agent_registry.py` |

## Phase 3 — DONE (commit `6f21376`, then P3-3/P3-4 commit `7d0071a`)

| ID | Item | Status | Proof |
|---|---|---|---|
| P3-1 | Test execution | **DONE** | `app/services/test_runner.py` + `test_execution.py`, model `test_run.py`. `tests/test_test_runner.py`, `tests/test_task_test_runs.py`. Verified live in browser (real pytest + npm runs, including a genuine Windows `npm.cmd` failure). |
| P3-2 | Repository KG ↔ Git integration (commit SHA) | **DONE** | `knowledge_graph.py::_git_head_sha`. `tests/test_code_ingestion.py::test_ingest_repository_records_real_commit_sha` |
| P3-3 | Repository KG extraction breadth (imports/deps/test-mapping, parser-adapter framework) | **DONE — VERIFIED** | `app/services/code_ingestion.py`: `LanguageAdapter` ABC + `PythonAdapter`/`TypeScriptJavaScriptAdapter` registered in `_ADAPTERS` (the parser-adapter framework); each adapter now also extracts real imports (Python `ast.Import`/`ImportFrom`, TS/JS regex). `compute_relationships()` resolves same-repo relative imports to real files (`DEPENDS_ON`) and maps recognized test-file naming conventions to their target file (`TESTS`); `knowledge_graph.ingest_repository` writes both as real Neo4j relationships (external/unresolved imports still become `Module`+`IMPORTS`, unchanged). `tests/test_code_ingestion.py` (13 tests: adapter unit tests + a full ingest→Neo4j→`GET /knowledge/graph?graph_type=repository` round trip asserting the real `DEPENDS_ON`/`TESTS` edges come back). Deliberately out of scope per the roadmap's own sequencing: `CALLS` (call-graph) and endpoint/DB-model extraction — both explicitly deferred in `audit/04` §"Proposed implementation sequence" step 5. |
| P3-4 | Multi-turn conversation (`TaskMessage`) | **DONE — VERIFIED (backend)** | Independently re-verified end-to-end this pass — no defects found in the existing implementation (`app/services/task_execution.py::execute_followup`/`app/api/routes/tasks.py` messages routes), only a prior total absence of test coverage. New `tests/test_task_messages.py` (7 tests): message persistence/ordering on a fresh task; a real two-turn round trip against a real git worktree (start → real file change → follow-up → worktree genuinely resumed, second real file added, real `AGENT` message recorded, `GET /messages` returns both turns in order); honest `SYSTEM`-message failure when there's no workspace to resume; 409 on a followup while already running; 403 for a viewer role and for a non-project-member; 401 unauthenticated. Frontend wiring (Task Center composer/UI) was not re-audited in this pass — backend is the verified scope. |
| P3-5 | Review comments | **DONE** | `app/models/review_comment.py`, routes in `tasks.py`. `tests/test_review_comments.py`. Verified live in browser. |
| P3-6 | Planning & Approval gate | **DONE (Approval half only)** | `app/models/approval.py`, `app/api/routes/approvals.py`. `tests/test_approvals.py`. Verified live in browser. **No `Plan` entity was built** — there is no planning-gate-before-execution step, only post-hoc approval of an already-opened PR. |

## Phase 4 — DONE (commit `da5accb`)

| ID | Item | Proof |
|---|---|---|
| P4-1 | Resolve the search-mix design question | **Resolved**, not just scheduled around: local Ollama (`nomic-embed-text`) embeddings + pgvector, kept separate from the Neo4j graph. See `DECISION_REGISTER.md`. |
| P4-2 | Document ingestion + chunking | `app/services/document_chunking.py` (character-window chunking), `Document`/`DocumentChunk` models. Scoped to plain text/Markdown content submitted via the API — no PDF/DOCX/HTML parsing. `tests/test_document_chunking.py` |
| P4-3 | Embedding + vector storage | `app/services/embeddings.py` (real Ollama `nomic-embed-text` calls), `pgvector` Postgres extension + HNSW cosine index (migration `8a0dcf3b06fb`). Dev Postgres image swapped to `pgvector/pgvector:pg16` (same data volume). `tests/test_documents.py` |
| P4-4 | Retrieval + RAG pipeline | `app/services/document_retrieval.py::retrieve_relevant_chunks`/`build_rag_context`, wired into `task_execution.py::_build_prompt_with_rag_context`. New `POST /projects/{id}/documents/search` endpoint. Verified live via curl: real ingestion → real embedding → real cosine-similarity retrieval with a genuine score. |

Not built in Phase 4: PDF/DOCX/HTML document ingestion, a reranking step, citation UI (the frontend
`knowledge-graph.component.ts`/`repository-intelligence.component.ts` are still 100% `MockDataService`
and were not wired to real document endpoints — only the backend RAG pipeline itself was built and
wired into task execution).

## Phase 5 — PARTIAL (P5-1/P5-2/P5-3 done; P5-4 not started)

| ID | Item | Status | Proof |
|---|---|---|---|
| P5-1 | Orchestration engine: dependency-aware scheduling, real parallel execution where safe, capability-based agent assignment, shared workflow state | **DONE** | `app/services/workflow_execution.py` rewritten as "the Factory Supervisor": round-based scheduler over a workflow's steps — a step becomes "ready" once every step in its dependency set has genuinely `COMPLETED`. Explicit `Task.depends_on_step_orders` (nullable `list[int]`, new column) opts a step into a *smaller* dependency set than "every prior step"; when two or more steps in the same round are ready, each runs in its own real thread + its own DB session (SQLAlchemy sessions aren't thread-safe) — genuine concurrent execution, not cosmetic reordering. `Task.required_capability` (new column) triggers real capability-based auto-assignment (`app/services/agent_assignment.py::select_connection`, matching `Agent.capabilities` from the Agent Registry) with an honest escalation error (step fails, never silently proceeds) when nothing eligible is connected. `Workflow.shared_context` (new JSON column) folds a real prior step's real output into a dependent step's prompt — **only** for steps that explicitly declare a dependency (`depends_on_step_orders is not None`), so a workflow using none of this is byte-for-byte unchanged from pre-Phase-5 behavior (all 10 pre-existing `test_workflows.py` tests pass unmodified). `tests/test_orchestration.py` (capability assignment success/honest-escalation, true parallel execution proven with a real multi-thread barrier rendezvous, shared-context injection, dependency-declaration validation). |
| P5-2 | Agent replacement / resumable handoff | **DONE, with an honestly documented limitation** | `app/models/orchestration.py::TaskHandoff` (versioned handover package, immutable per handoff — a second handoff is a new row) + `TaskExecutionAttempt` (immutable per-real-adapter-invocation audit log). `app/services/handoff.py`: `build_handover_package` snapshots the task's real git diff/output/test results/review comments/conversation into a JSON package; `resume_task_with_handoff` resumes the **same real git worktree/branch** (`git_worktree.resume_worktree`) under a **different** connection/adapter, with a prompt built from that real package — a genuine continuation, not a stateless restart. `POST /projects/{id}/tasks/{id}/handoff` (human-triggered) and `GET .../handoffs`, `GET .../attempts`. **Limitation, matching `audit/03` B9**: no adapter (Claude Code/Codex/Gemini/Qwen CLI, or the HTTP adapters) exposes a real resumable session ID — every invocation is a fresh process/API call, so `TaskHandoff.package["provider_session_id"]` is always `null` with an explanatory docstring; this is the "context-based continuation" fallback path the roadmap explicitly allows, not native session resume. `tests/test_orchestration.py::test_human_triggered_handoff_resumes_the_real_worktree_with_a_different_agent` (Claude Code fails mid-task against a real git worktree → human hands off to Codex → Codex genuinely resumes the same worktree, sees the first agent's real partial file, completes — 2 real `TaskExecutionAttempt` rows, 1 real `TaskHandoff` row), plus a 409 test for handing off a currently-running task. |
| P5-3 | Policy-controlled provider routing/fallback | **DONE, deliberately narrow scope** | `app/models/orchestration.py::ProviderRoutingPolicy` (org-scoped, optionally capability-scoped, ordered `fallback_chain` of runtime slugs). `agent_assignment.select_connection` consults the matching policy (capability-specific first, else the org-wide default) to order candidates, falling back to registry order when no policy exists. Used by both P5-1's auto-assignment and P5-1's automatic retry-on-failure (a failed step with `max_retries` set automatically creates an **automatic** `TaskHandoff` to the next eligible connection in the chain and resumes). `POST`/`GET`/`DELETE /organizations/{id}/routing-policies` (org-admin only to write). **Deliberately not built**: cost-based routing, continuous provider health monitoring/circuit-breaking, versioned/pinned model profiles — none of these were asked for by the roadmap's own P5-3 description beyond "policy-controlled... fallback chains," and bolting them on would be scope creep; see `DECISION_REGISTER.md`. `tests/test_orchestration.py::test_step_retries_with_automatic_fallback_to_a_different_connection`, `test_routing_policy_orders_the_fallback_chain`, `test_non_org_admin_cannot_create_routing_policy`. |
| P5-4 (B4) | Graph-powered agent/context retrieval | **NOT STARTED** | Needs its own design pass — per `audit/03-AGENT_ORCHESTRATION_AUDIT.md`, this depends on a tool-calling mechanism in the agent runtime adapters that doesn't exist yet (today, every adapter gets one flat prompt string, not an interactive tool loop that could query the knowledge graph mid-execution). Deferred rather than half-built against a dependency that isn't there. |

See `PRD_REQUIREMENT_INDEX.md` for the full task-ID table; see
`audit/09-SOFTWARE_FACTORY_REMAINING_ROADMAP.md` §Phase 5/6 for objectives.

## Phase 6 — NOT STARTED

See `PRD_REQUIREMENT_INDEX.md` for the full task-ID table; see
`audit/09-SOFTWARE_FACTORY_REMAINING_ROADMAP.md` §Phase 5/6 for objectives.

## Pre-existing uncommitted work — NOT part of any phase, do not touch or "fix" as phase work

This was sitting in the working tree before Phase 0 started and remains uncommitted and untouched
through Phase 3. Every phase commit was built with surgical git staging specifically to avoid
disturbing or accidentally claiming this work (see `DECISION_REGISTER.md`). Do not assume it is
broken just because it's uncommitted, and do not fold fixing it into an unrelated phase's scope:

- `backend/app/services/model_catalog_service.py` (new, untracked)
- `backend/app/services/repository_intelligence_service.py`, `graphify_adapter.py` (new, untracked)
- `backend/app/models/repository_intelligence.py`, `backend/app/schemas/repository_intelligence.py`,
  `backend/app/api/routes/repository_intelligence.py` (new, untracked)
- `backend/alembic/versions/a1b2c3d4e5f6_add_repository_intelligence_tables.py`,
  `51e63e34dee0_add_task_selected_model_and_execution_.py`,
  `e8b1c2d3f4a5_add_task_knowledge_context.py` (new, untracked migrations)
- `frontend/src/app/shared/model-picker/` (new, untracked component)
- `frontend/src/app/core/org/repository-intelligence.{models,service}.ts` (new, untracked)
- Modified-but-uncommitted: `backend/app/models/task.py`, `task_message.py`, `backend/app/schemas/task.py`,
  `backend/app/services/agent_runtime/{base,registry}.py`, `code_ingestion.py`, `git_sync.py`,
  parts of `task_execution.py`, `tasks.py` route file, `docker-compose.yml`, `backend/Dockerfile`,
  the model-picker/agent-reassignment portions of `task-workspace.component.{ts,html,scss}`,
  `agent-runtime.{models,service}.ts`, `knowledge.service.ts`, `task.{models,service}.ts`,
  `project-workspace.component.*`, `repository-intelligence.component.*`,
  `knowledge-graph.component.*`.
- **The 14 pre-existing, unrelated test failures** (same count since Phase 0): all
  `TypeError: fake_streaming() got an unexpected keyword argument 'model'` — a stale test-fixture
  signature mismatch from this same uncommitted model-selection work, in
  `test_agent_runtimes.py`/`test_tasks.py`/`test_workflows.py`. Not caused by, and not fixed by, any
  phase commit. Confirmed stable at 14 across Phase 0 (140 passed), Phase 2 (152 passed), and
  Phase 3 (172 passed) full-suite runs — i.e. the failing set never changed, only the passing count
  grew by exactly what each phase added.

## Last full test-suite result

**182 passed, 14 failed** (`pytest -q`, ~229s), as of commit `da5accb` (Phase 4). The 14
failures are the same pre-existing set above — zero regressions from any phase's own work. (Phase 3
baseline was 172 passed, 14 failed at commit `6f21376`; the 10 additional passing tests are exactly
what Phase 4 added.)

**197 passed, 0 failed** (`pytest -q`, ~95s), in this clean worktree after the P3-3/P3-4 pass
(against `SF_TEST_DATABASE_URL=...sf_worktree_p3`, see the environment note above). The "same 14
failures" set from previous phases is **not reproducible in a clean worktree** — those 14
`fake_streaming()` signature-mismatch failures only exist in the main checkout, caused by its own
pre-existing *uncommitted* model-selection changes to `test_agent_runtimes.py`/`test_tasks.py`/
`test_workflows.py` (see the untouched list below); the committed test files at `6f21376`/`da5accb`
never had this mismatch. 197 = 182 (Phase 4 baseline) + 8 new `test_code_ingestion.py` tests (P3-3)
+ 7 new `test_task_messages.py` tests (P3-4).

**206 passed, 0 failed** (`pytest -q`, ~101s), after the Phase 5 (P5-1/P5-2/P5-3) commit `2b70be9`, same isolated
test database. 206 = 197 (P3-3/P3-4 baseline) + 9 new `tests/test_orchestration.py` tests. Verified
with a clean drop/recreate of the test database immediately before the run (model/migration changes
this phase added several columns and three new tables, and `conftest.py`'s `Base.metadata.create_all()`
only creates missing tables — it never `ALTER`s an existing one with a new column).
