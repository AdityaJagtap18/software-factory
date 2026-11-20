# 07 — Testing and Verification Report

Environment at time of audit: Windows, Python 3.13.5, backend `.venv` at `backend/.venv`, pytest 9.0.2. `docker ps` confirmed a running `softwarefactory-postgres-1` (postgres:16-alpine, port 5433) and a real local Docker daemon. No Neo4j instance was reachable at the app's configured `bolt://localhost:7688` (the `nexora-neo4j-1` container seen in `docker ps` listens on 7687/7474 for an unrelated project, not this one).

All commands below were run read-only against the test database `software_factory_test` (a separate database automatically created by `backend/tests/conftest.py`, truncated between tests) — never against the dev database `software_factory`. No destructive commands were run.

## Backend test suite — VERIFIED THIS AUDIT

Command: `cd backend && source .venv/Scripts/activate && python -m pytest -q`

**Result:**
```
112 passed, 4 skipped, 11 warnings in 78.81s (0:01:18)
```

Collection: `python -m pytest --collect-only -q` → **116 tests collected** across:
`test_agent_runtimes.py`, `test_auth.py`, `test_code_ingestion.py`, `test_dashboard.py`, `test_docker_sandbox.py`, `test_git_integration.py`, `test_git_worktree.py`, `test_knowledge.py`, `test_my_tasks.py`, `test_my_workflows.py`, `test_organizations_and_projects.py`, `test_presence.py`, `test_tasks.py`, `test_workflows.py`.

**Zero failures.** The 4 skips are honest, environment-gated skips, not disabled/broken tests:
- `backend/tests/test_knowledge.py::test_sync_and_query_a_real_graph_round_trip` and `::test_sync_is_idempotent` — both guarded by `requires_neo4j = pytest.mark.skipif(not _neo4j_available(), ...)` (file lines 6-13); skipped because Neo4j is not reachable in this environment (confirmed: `SF_NEO4J_URI=bolt://localhost:7688` in `.env`, nothing listening there per `docker ps`). The two *access-control* tests in the same file that don't need Neo4j — `test_viewer_without_project_access_cannot_sync`, `test_graph_endpoint_requires_project_access` — are **not** skipped and **passed**.
- One or more skips originate the same way in `backend/tests/test_code_ingestion.py` (also defines `requires_neo4j`) and `backend/tests/test_agent_runtimes.py:88` (`pytest.skip("claude CLI not installed on this machine")`) — confirmed by grep of all `skipif`/`pytest.skip` call sites in `backend/tests/`; exact per-file skip count not individually re-verified beyond the total (4) and the two attributed above.

Separately re-ran `backend/tests/test_docker_sandbox.py` alone to confirm it against the real Docker daemon: **6 passed in 28.51s**, including a test that proves `--network none` genuinely blocks DNS resolution from inside the container, and a test that proves cancellation actually kills the container process (elapsed time assertion `< 20s` against a `sleep 30`, not just a flag flip). These 6 are already included in the "112 passed" total above, not additional.

### What the suite actually proves (traced route → service → DB/process, not just "it's green")

| Test file | What it asserts, read end-to-end |
|---|---|
| `test_auth.py` | Register/login/refresh/logout against real bcrypt + JWT + hashed refresh-token rows |
| `test_organizations_and_projects.py` | Org creation makes creator admin; non-member/non-admin 403s; last-admin-cannot-be-demoted invariant; project creation visibility isolation; **cross-organization isolation** |
| `test_tasks.py` | Viewer cannot create task (RBAC); starting a task with no connection, or on a machine with no CLI installed, fails *honestly* (no fabricated success); successful execution marks task completed with real adapter output; cross-org connection rejected; cancel semantics; SSE stream endpoint reaches a terminal state; real Git worktree creation, real diff collection on empty vs. real changes, real branch push + PR open, PR failure doesn't overturn task success, branch protection lookup recorded/failure handled honestly |
| `test_workflows.py` | Multi-step workflows; a step's failure stops the remaining steps from running; cancel mid-step; delete cascades to step tasks |
| `test_presence.py` | WebSocket presence rejects invalid token and no-access user; a second viewer's join triggers a real broadcast to the first viewer (two real sockets, not a simulated count) |
| `test_knowledge.py` | Sync writes genuine Neo4j nodes/edges and the graph read reflects them back (SKIPPED here — no Neo4j); sync is idempotent (SKIPPED); **but** the 403 access-control assertions on both the sync and graph endpoints ran and passed with no Neo4j needed |
| `test_docker_sandbox.py` | Real container execution, real network isolation, real resource-limited execution, real honest failure (`exit 7`), real cancellation that kills the container — all against the actual local Docker daemon, not mocked |
| `test_git_integration.py` | GitHub App / provider logic (mocked GitHub API, not a live GitHub call) |
| `test_agent_runtimes.py` | CLI detection honestly reports not-connected when a CLI isn't on PATH; one test explicitly skips when `claude` CLI isn't installed rather than faking success |
| `test_dashboard.py`, `test_my_tasks.py`, `test_my_workflows.py` | Cross-project aggregation only includes projects the requesting user can actually see (via `visible_project_ids`), including "genuinely empty for a user with no access" |
| `test_code_ingestion.py` | Neo4j-gated portions; not individually itemized in this pass |
| `test_git_worktree.py` | Worktree preparation failure modes |

## Frontend type-check — VERIFIED THIS AUDIT

Command: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`

**Result: clean — no output, exit success.** The Angular 18+ standalone app's application source compiles with no type errors under its own `tsconfig.app.json`. This checks types only; it does not run unit tests, the Angular build pipeline (`ng build`), or lint.

No `ng test` / Karma/Jasmine run was attempted — not requested to run destructive or long-running browser test launches, and no quick evidence was gathered on current frontend unit-test pass/fail state. **NOT VERIFIED.**

No `ng build --configuration=production` was attempted (would be a heavier, longer-running build step not requested as a hard requirement once `tsc --noEmit` already gave a clean type-check signal). **NOT VERIFIED** for a full production bundle build.

## Coverage gaps / NOT VERIFIED in this audit

- **Knowledge graph round-trip against real Neo4j** — code path exists and is exercised by `test_knowledge.py`'s two Neo4j-gated tests, but this environment has no reachable Neo4j for the Software Factory app (confirmed via `docker ps` + `.env` port mismatch), so those two tests could not be observed passing here. Status: IMPLEMENTED BUT NOT VERIFIED (the test code and the service code both exist and read as correct; they simply did not execute this session).
- **Live GitHub App / live Git provider calls** — `test_git_integration.py` passed, but against mocked HTTP, not a live GitHub App installation. Status: IMPLEMENTED BUT NOT VERIFIED for the live integration path.
- **Non-Docker agent-runtime CLIs (Claude Code, Codex, Gemini CLI, Qwen) actually executing** — these adapters' "honest failure" paths are exercised (CLI not installed → reported not-connected), but no test in this suite demonstrates a real, successful invocation of any of those four CLIs end-to-end (only Docker Sandbox has a real-success test, per that file's own docstring: "the first non-mocked task-execution test in this project whose honest, non-mocked outcome is a real success"). Status: PARTIALLY IMPLEMENTED / NOT VERIFIED for real success paths on those four runtimes.
- **Multi-replica presence / horizontal scaling** — `presence.py`'s own docstring states it is in-memory, per-process, and does not coordinate across backend replicas. Single-process presence is VERIFIED (via `test_presence.py`); multi-instance behavior is explicitly NOT IMPLEMENTED, not merely untested.
- **Frontend unit/e2e tests** — NOT VERIFIED (not run this session).
- **Load/performance testing, security penetration testing** — NOT VERIFIED / NOT IMPLEMENTED (no such suite found in the repository).

## Summary

| Area | Status |
|---|---|
| Backend pytest suite | **112 passed / 4 skipped / 0 failed** — VERIFIED THIS AUDIT (real command run, output pasted above) |
| Docker Sandbox real-isolation tests | **6/6 passed** — VERIFIED THIS AUDIT |
| Knowledge-graph Neo4j round-trip tests | NOT VERIFIED (Neo4j unreachable in this environment; tests skip honestly rather than fail) |
| Frontend type-check (`tsc --noEmit`) | **Clean** — VERIFIED THIS AUDIT |
| Frontend unit tests / production build | NOT VERIFIED (not run) |
| Live GitHub integration | NOT VERIFIED (suite uses mocked HTTP) |
| Multi-user / cross-org isolation tests | **Passed** — VERIFIED THIS AUDIT (`test_cross_organization_isolation` and related RBAC tests) |
