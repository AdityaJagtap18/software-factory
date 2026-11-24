# Project Context — Software Factory

Durable map of the system. Read this before touching code; it points to the audit doc with full
depth instead of repeating it. Keep this file in sync only when an architectural fact changes — not
on every task.

## What this is

Software Factory is an AI-powered multi-agent software-engineering platform: users submit natural-
language tasks against a connected Git repository, a coding-agent CLI (Claude Code, Codex, Gemini
CLI, Qwen, a Docker-sandboxed custom runtime) executes the task in a real git worktree, and the
platform opens a real GitHub pull request from the result. Organizations/Projects/RBAC wrap all of
it. See `audit/01-SOFTWARE_FACTORY_CURRENT_STATE.md` for the full feature-by-feature status matrix
and `audit/02-SOFTWARE_FACTORY_ARCHITECTURE.md` for the as-built architecture with sequence diagrams.

## Stack

- **Backend:** FastAPI + SQLAlchemy + PostgreSQL (Alembic migrations), single-process ASGI
  (`uvicorn app.main:app`). Background task/workflow execution runs as Python `threading.Thread`
  **inside the same process** — no Celery/RQ/Temporal worker, no broker.
- **Frontend:** Angular 18+, standalone components, signals (not NgRx/RxJS-heavy state).
- **Knowledge graph:** Neo4j (`bolt://localhost:7688` in dev), one cached driver singleton in
  `backend/app/services/knowledge_graph.py`, accessed only through `GraphAccessService`
  (`backend/app/services/graph_access.py`, added Phase 2).
- **RAG / document knowledge (Phase 4):** `pgvector` extension on the same Postgres (dev image
  `pgvector/pgvector:pg16`), embeddings via this project's own local Ollama instance
  (`nomic-embed-text`, `backend/app/services/embeddings.py`) — no external API key, no separate
  vector DB. Deliberately separate from the Neo4j Engineering Knowledge Graph (see
  `DECISION_REGISTER.md`). Scoped to plain text/Markdown content only — no PDF/DOCX/OCR.
- **No message broker exists anywhere in this stack.**
- Containers: `postgres`, `neo4j`, `backend`, `frontend` (`docker-compose.yml`). No worker/queue
  container.

## Where things live

| Subsystem | Code |
|---|---|
| Auth / RBAC | `backend/app/core/security.py`, `backend/app/api/deps.py`, `backend/app/services/access.py` |
| Rate limiting | `backend/app/core/rate_limit.py` (in-memory, single-process only — Phase 0) |
| Org/Project/membership | `backend/app/models/organization.py`, `project.py`; routes `organizations.py`, `projects.py` |
| Agent runtime adapters | `backend/app/services/agent_runtime/{base,registry,adapters}.py` — `ClaudeCodeAdapter`, `CodexAdapter`, `GeminiCliAdapter`, `QwenAdapter`, `DockerSandboxAdapter`, `CustomAdapter` |
| Agent Registry (Phase 2) | `backend/app/models/agent.py`, `backend/app/services/agent_registry.py` — `GET /agents` |
| Task execution | `backend/app/services/task_execution.py` (`execute_task`, `_run_adapter_and_finish`) — the central orchestration function; runs in a background thread |
| Git worktree / diff / PR | `backend/app/services/git_worktree.py`, `backend/app/services/git_provider/github_app.py`, `backend/app/services/git_webhook.py` |
| Test execution (P3-1) | `backend/app/services/test_runner.py` (detect+run pytest/npm), `backend/app/services/test_execution.py` (`run_tests_for_task`), model `backend/app/models/test_run.py` |
| RAG / document knowledge (Phase 4) | `backend/app/services/document_chunking.py`, `embeddings.py`, `document_retrieval.py` (ingest/retrieve), models `backend/app/models/document.py`, routes `backend/app/api/routes/documents.py` — wired into task prompts via `task_execution.py::_build_prompt_with_rag_context` |
| Knowledge graph | `backend/app/services/knowledge_graph.py`, `code_ingestion.py`, `graph_access.py`; routes `backend/app/api/routes/knowledge.py` |
| Review comments (P3-5) | `backend/app/models/review_comment.py`, routes appended to `backend/app/api/routes/tasks.py` |
| Approvals (P3-6) | `backend/app/models/approval.py`, `backend/app/api/routes/approvals.py` |
| Presence (WebSocket) | `backend/app/services/presence.py`, route `presence.py` — single-process only, no cross-replica fan-out |
| Credential encryption | `backend/app/core/crypto.py` (Fernet, keyed by `SF_CREDENTIAL_ENCRYPTION_KEY`) |
| Audit log | `backend/app/services/audit.py`, model `audit.py` — backend only, no frontend viewer |
| Frontend task workspace | `frontend/src/app/features/task-workspace/` — real diff viewer, review comments, test runs, PR panel |
| Frontend approvals | `frontend/src/app/features/approvals/` — real since Phase 3 (was `MockDataService`) |
| Frontend mock-only features | `agents`, `artifacts`, `code-review`, `knowledge`, `monitoring`, `project-workspace` (partially), `prompts`, `providers`, `repository-intelligence`, `settings` still import `core/mock-data.service.ts` — do not assume any UI under `features/` is real without checking for this import first |

## Architectural invariants — do not violate these

1. **GraphAccessService has no method that accepts a caller-supplied `project_id`.** Scope is always
   derived from an already-authenticated `ProjectContext` (`from_project_context`) or a trusted
   server-internal `Project` object already loaded through its own auth path (`from_project`). This
   is structurally tested (`backend/tests/test_graph_access.py`). Adding a new graph read/write that
   takes a bare `project_id` parameter reintroduces the exact gap Phase 2 closed — don't.
2. **RBAC model:** `OrgRole` (admin/member) and `ProjectRole` (`PROJECT_ADMIN`, `DEVELOPER`,
   `REVIEWER`, `VIEWER`). Org-admin implicitly gets `PROJECT_ADMIN` on any project in that org
   (`effective_project_role`). Route-level enforcement is always `ctx.require_role({...})`; the
   common elevated set is `MANAGE_ROLES = {PROJECT_ADMIN, DEVELOPER}`, defined once per route file
   that needs it (currently in `tasks.py`; `approvals.py` defines its own `DECIDE_ROLES` with the
   same two roles).
3. **"Never fabricate, never mock a result."** A task is marked `COMPLETED` only when the adapter
   itself returned `succeeded=True`. Honest-failure is a first-class state everywhere — test runs,
   approvals, PR creation, graph ingestion, sandboxing all report `ran=False`/empty/`"none"` rather
   than inventing a plausible-looking success. When extending any of these, preserve this — do not
   add a fallback that silently "passes" when the real operation couldn't run.
4. **PR state is the one source of truth for merge actions.** Approvals (P3-6) deliberately do not
   duplicate the real PR-merge action that already exists in `tasks.py`'s `merge_task_pull_request` —
   an `Approval` row records a decision, it does not itself merge anything. Don't build a second path
   that also merges.
5. **Alembic migrations autogenerate a spurious, unrelated `op.drop_index('ix_task_messages_task_id', ...)`
   on this tree right now**, from already-uncommitted drift elsewhere. Every new migration must have
   this manually stripped from both `upgrade()` and `downgrade()` before it's applied — see
   `DECISION_REGISTER.md`.
6. **Background execution is in-process threading, not a queue.** Any new long-running operation
   triggered from a route (like the test-run hook) must either run synchronously fast enough for an
   HTTP response, or spawn its own `threading.Thread`/reuse the existing background-thread pattern in
   `task_execution.py`. There is no Celery/RQ to hand work to.
7. **Commit ordering inside `_run_adapter_and_finish` matters.** Any hook that does its own
   intermediate `db.commit()` must run *after* the task's status-defining fields (PR state, etc.) are
   fully set, immediately before the function's own final commit — not before. See
   `DECISION_REGISTER.md` for the race condition this caused once already.
8. **Windows dev environment:** `subprocess.run(["npm", ...])` fails with `WinError 2` on Windows
   unless you use `"npm.cmd"` (no shell resolution of `.cmd` files via bare `CreateProcess`). Check
   `platform.system()` before invoking any Node-ecosystem CLI from Python.

## Known, deliberate non-features (don't "fix" these as bugs)

- Branch protection rules are **read and displayed only, never enforced** by this backend (by
  design — GitHub's own merge button is the real gate).
- The four LLM-CLI adapters run **directly on the backend host**, not sandboxed, unless a
  `SF_*_SANDBOX_IMAGE` env var is set (currently none are — Phase 2 P2-3 built the plumbing only).
- No prompt-injection or agent-output-safety layer exists anywhere (`audit/06-SECURITY_AND_GOVERNANCE_AUDIT.md` §4).
- The Neo4j knowledge graph only extracts files + top-level Python/TS/JS symbols; no imports, no
  call graph, no commit history beyond a single `commit_sha` field (Phase 3 P3-2). This is Phase 3
  P3-3 scope, not yet done.
- There is **no RAG/document/vector system anywhere** — see `audit/05-RAG_AND_KNOWLEDGE_AUDIT.md`.
  Phase 4 of the roadmap addresses this, contingent on an undecided design question (P4-1).

## Where to go for depth

- Full current-state matrix: `audit/01-SOFTWARE_FACTORY_CURRENT_STATE.md`
- Architecture + sequence diagrams: `audit/02-SOFTWARE_FACTORY_ARCHITECTURE.md`
- Agent orchestration / provider integration detail: `audit/03-AGENT_ORCHESTRATION_AUDIT.md`
- Knowledge graph detail + proposed sequence: `audit/04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md`
- RAG/document-knowledge audit (confirms nothing exists): `audit/05-RAG_AND_KNOWLEDGE_AUDIT.md`
- Security/governance detail: `audit/06-SECURITY_AND_GOVERNANCE_AUDIT.md`
- Test suite evidence: `audit/07-TESTING_AND_VERIFICATION_REPORT.md`
- Gap analysis: `audit/08-IMPLEMENTATION_GAP_ANALYSIS.md`
- **The roadmap (phase/task-ID source of truth):** `audit/09-SOFTWARE_FACTORY_REMAINING_ROADMAP.md`
- Engineering handover narrative: `audit/10-ENGINEERING_HANDOVER_SUMMARY.md`
- Chronological change record with full verification evidence: `audit/11-IMPLEMENTATION_CHANGELOG.md`

For "is X done and how do I know," check `IMPLEMENTATION_STATE.md` first — it's the condensed,
current answer; the audit docs are the evidence trail behind it.
