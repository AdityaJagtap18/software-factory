# Decision Register

Real architectural/scoping decisions made during Phase 0/2/3 implementation that aren't obvious
from reading the code alone. Each entry: Decision / Why / Implication for future work. Append new
entries at the top (newest first) as future phases make their own non-obvious calls.

---

### P3-3/P3-4 — removed a broken `repository_intelligence` import from `main.py`; isolated test DB for this worktree
**Decision:** Deleted the `repository_intelligence` import and `app.include_router(...)` call from
`backend/app/main.py`. Also ran this pass's tests against a dedicated local Postgres database
(`sf_worktree_p3`) instead of the shared `software_factory_test` database.
**Why:** The committed `main.py` (as of the Phase 4 commit, `da5accb`) imports
`app.api.routes.repository_intelligence` — a module that was never committed; it only exists as
pre-existing, *uncommitted* work sitting in the separate main checkout at
`C:\Users\Admin\Desktop\Software Factory`. On a clean checkout of this branch (this worktree), that
import fails and the app cannot boot at all — no route works, no test can run, nothing. This is a
real regression in the committed tree (most likely a staging mistake in an earlier phase commit,
done from the main checkout where the uncommitted file happened to also be present on disk), not a
design choice to revisit. Per this session's explicit instruction to leave the main checkout's
uncommitted work untouched, the fix only ever removes the dangling reference in the committed file;
the uncommitted `repository_intelligence.py`/model/schema files themselves were not read, modified,
or committed. Separately, the shared Postgres test database already has a `tasks.knowledge_context
NOT NULL` column applied directly by the main checkout's own uncommitted Alembic migration — this
worktree's `Task` model has no such column, so any test inserting a `Task` against that shared DB
fails with a `NotNullViolation` that has nothing to do with this phase's own changes. Pointing
`SF_TEST_DATABASE_URL` at a fresh, separate database sidesteps that contamination without touching
the shared DB's schema (which the other checkout's in-progress work may still depend on).
**Implication:** Whoever next commits the `repository_intelligence` feature for real must re-add its
import/`include_router` line to `main.py` as part of that same commit (not rely on it silently still
being there). Any other worktree/session hitting the same `knowledge_context` `NotNullViolation`
against the shared test DB should also point `SF_TEST_DATABASE_URL` at its own database rather than
"fixing" the shared one's schema — that schema belongs to whichever session is actively building the
uncommitted model-selection/repository-intelligence work.

### P4-1 — the RAG search-mix decision: local Ollama embeddings + pgvector, kept separate from the Neo4j graph
**Decision:** Resolved the roadmap's open "what search mix" question (P4-1) as: (1) document scope
limited to plain text/Markdown submitted directly as API content — no PDF/DOCX/HTML parsing was
built; (2) embeddings via this project's own local Ollama instance running `nomic-embed-text`
(768-dim), the same `OLLAMA_HOST` the Qwen adapter already targets — no external API key, no new
network dependency; (3) vector storage via the `pgvector` Postgres extension (the dev Postgres
container's image was swapped from `postgres:16-alpine` to `pgvector/pgvector:pg16`, same data
volume preserved); (4) retrieval is a separate subsystem from the Neo4j Engineering/Repository
Knowledge Graph — no shared tables, no shared service — per `audit/05-RAG_AND_KNOWLEDGE_AUDIT.md`'s
explicit warning not to conflate "document knowledge" with "code-structure graph."
**Why:** `nomic-embed-text` was already pulled and reachable on a *different* project's Ollama
container on this dev machine (port 11435) — that one was deliberately **not** used, since it isn't
actually part of this codebase's infrastructure and could disappear at any time. Instead the model
was pulled onto Software Factory's own primary Ollama instance (port 11434, `OLLAMA_HOST` default),
so the dependency is real and owned by this project. `pgvector` was chosen over a separate vector DB
because Postgres was already a hard dependency; `pgvector/pgvector:pg16` is a maintained drop-in for
`postgres:16-alpine` with an identical data directory format, confirmed by recreating the running dev
container against the existing `sf_postgres_data` volume and verifying `SELECT count(*) FROM users`
returned the pre-existing row count unchanged.
**Implication:** PDF/DOCX ingestion, OCR, and a swap to a stronger/remote embedding model are all
explicitly out of scope for what shipped — don't assume they exist. If a future phase changes the
embedding model, every existing `document_chunks.embedding` value must be recomputed (the column is
dimension-typed); there is no migration path that reuses old vectors across models. The test suite's
`_ensure_database_exists()` now also runs `CREATE EXTENSION IF NOT EXISTS vector` for the
non-Alembic, `Base.metadata.create_all()`-built test database — a future new Postgres extension
needs the same test-conftest treatment, not just an Alembic migration.

### Approvals do not duplicate the PR-merge action
**Decision:** The Phase 3 `Approval` model/route records a governance decision only. It does not
itself merge, push, or otherwise act on a pull request.
**Why:** A real PR-merge action already exists (`tasks.py::merge_task_pull_request`). Building a
second path that also merges would create two sources of truth for the same Git action.
**Implication:** If a future "approval gates execution" flow (the still-missing `Plan` entity, P3-6
remainder) is built, wire it to call the *existing* merge/execution entry points rather than adding
a new one inside `approvals.py`.

### GraphAccessService has no method with a caller-supplied `project_id`
**Decision:** Every method derives scope from `from_project_context(ctx)` or `from_project(project)`
— never from a bare `project_id` argument.
**Why:** The pre-Phase-2 audit (`04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` §3.5) found that
`knowledge_context.py` had already added a second raw-Cypher caller bypassing the one existing
service's informal convention — exactly the risk a caller-supplied id creates (nothing stops a
future caller from passing an arbitrary project it doesn't actually have access to).
**Implication:** Any new Neo4j-touching code must go through `GraphAccessService`, obtained from an
already-authorized `ProjectContext` or an already-loaded `Project`. This is tested
(`test_graph_access.py` asserts no method has a `project_id` parameter) — a new method that violates
this will need that test updated, which should be treated as a signal to reconsider the design, not
just patch the test.

### Test-execution hook runs *after* the PR section, not before
**Decision:** In `task_execution.py::_run_adapter_and_finish`, the automatic post-completion test run
(P3-1) is placed immediately before the function's own final `db.commit()`, after the entire
PR-open/push try/except block.
**Why:** It originally ran *before* that block. `run_tests_for_task` does its own intermediate
`db.commit()`; since `task.status` had already been set to `COMPLETED` earlier in the function, that
intermediate commit prematurely persisted "completed" to the DB while the PR section was still
executing in the same background thread. A polling test helper (`_wait_for_terminal_status`) then
observed "completed" and stopped polling before the PR fields were populated — an intermittent race,
caught only by live end-to-end browser verification, not by the unit tests alone.
**Implication:** Any future hook added to this function that does its own commit must go last, right
before the function's own final commit — never between the status-setting code and the PR section.

### `npm.cmd`, not `npm`, on Windows
**Decision:** `test_runner.py` checks `platform.system() == "Windows"` and uses `"npm.cmd"` instead
of `"npm"` when invoking Node test suites via `subprocess.run`.
**Why:** On Windows, `npm` is actually `npm.cmd`/`npm.ps1`; Python's `subprocess` without
`shell=True` calls `CreateProcess` directly, which cannot resolve `.cmd` files the way a POSIX shell
resolves `PATH`/`PATHEXT`. Caught live: a real task's "Run Tests" button produced `WinError 2` before
the fix.
**Implication:** Any new code that shells out to a Node-ecosystem CLI (`npm`, `npx`, `yarn`, etc.)
from Python needs the same `platform.system()` check. This is a dev-machine-specific gotcha that
won't surface in CI if CI runs Linux — don't assume "tests pass in CI" proves this is handled.

### Alembic autogenerate drift — strip the spurious `task_messages` index drop every time
**Decision:** Every `alembic revision --autogenerate` run on this tree currently picks up a spurious,
unrelated `op.drop_index('ix_task_messages_task_id', table_name='task_messages')` and must have it
manually removed from both `upgrade()` and `downgrade()` before the migration is used.
**Why:** The drift comes from already-uncommitted schema changes elsewhere in the working tree (see
`IMPLEMENTATION_STATE.md`'s "pre-existing uncommitted work" list), unrelated to whatever table the
new migration is actually adding. This has now happened 3+ times (approvals, review_comments,
test_runs migrations).
**Implication:** Do not trust `alembic revision --autogenerate` output verbatim on this tree until
that underlying uncommitted drift is itself committed or reconciled. Always diff the generated
migration against "what I actually intended to add" before applying it.

### Surgical git staging to keep phase commits isolated
**Decision:** When a file this phase needs to touch also contains substantial pre-existing,
unrelated uncommitted work (e.g. `task_execution.py`, `models/__init__.py`,
`task-workspace.component.{ts,html,scss}`, `tasks.py`), the commit is built by: extracting the HEAD
version (`git show HEAD:<path>`), applying *only* this phase's specific edits on top of that HEAD
copy, verifying via `diff` against HEAD that the result isolates exactly the intended changes,
`git add`-ing that isolated version, then restoring the full working-tree file (with all the other
unrelated uncommitted work) via a backup copy taken before the swap.
**Why:** No explicit instruction named these exact files as safe to commit as a mixed diff (unlike
an earlier session where the user had explicitly named specific files). Full isolation is the safer
default whenever that explicit naming is absent — it avoids accidentally committing someone else's
in-progress, unreviewed work under this phase's commit message, and avoids disturbing files another
part of the system may still be actively changing.
**Implication:** Any future phase that touches a file already showing unrelated `git diff` content
should use this same technique rather than a blanket `git add <file>`. Always run `git diff --stat`
on every touched file before staging to check whether it's clean or needs this treatance.

### Local `.env` secrets were not rotated in Phase 0
**Decision:** This developer's own local `backend/.env` (`SF_JWT_SECRET`, `SF_CREDENTIAL_ENCRYPTION_KEY`,
`SF_DEV_QUICK_LOGIN_ENABLED=true`) was left exactly as-is; Phase 0 added a *structural* guard
(`_validate_non_local_settings`) instead of rotating these values.
**Why:** This `.env` is gitignored, never leaves the one local-dev machine, and is intentional dev
convenience. Rotating it would invalidate every live local session/credential for zero security
benefit, since the structural guard already prevents these exact placeholder values from being used
in any non-local environment.
**Implication:** Don't "fix" this local `.env` as a follow-up security task — it's working as
intended. The actual risk (a non-local deployment inheriting these placeholders) is the thing that's
closed, verified by `tests/test_config_security.py`.

### P2-3 sandboxing is intentionally inert everywhere today
**Decision:** The Docker-sandboxed-CLI-execution plumbing for Claude Code/Codex/Gemini CLI/Qwen was
built and verified against the real Docker daemon, but all four `SF_*_SANDBOX_IMAGE` settings ship
empty by default, so every adapter still runs directly on the backend host exactly as before.
**Why:** No real Docker image with any of those four CLIs actually installed exists yet in this
repo/environment. Claiming the sandboxing was "done" without one would be exactly the kind of
fabricated-success claim this project's stated principle rules out.
**Implication:** Building and verifying four real per-CLI Docker images is its own concrete,
separately-scoped follow-up — not a small addendum to whatever phase touches this area next. Don't
mark P2-3 fully DONE until those images exist and are verified; the roadmap doc already states this
caveat explicitly, keep it that way.
