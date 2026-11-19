# Software Factory — Backend (Phases 1–3: Foundation, Connectivity & Execution)

FastAPI + PostgreSQL backend implementing real authentication, organizations,
membership, RBAC, projects, workspaces, coding-agent runtime connectivity,
and task execution — the foundation the rest of the Software Factory
execution spec (orchestration, knowledge graph, etc.) builds on.

## What's implemented

### Phase 1 — Product foundation
- **Auth**: register, login (JWT access token + opaque refresh token with
  rotation and revocation), `/auth/me`, logout.
- **Organizations**: create, list mine, members (invite/list/change
  role/remove), with an `org_admin` / `member` role model enforced on every
  endpoint. The last `org_admin` of an organization cannot be demoted or
  removed.
- **Projects & workspaces**: create/list/get/update, project membership
  (`project_admin` / `developer` / `reviewer` / `viewer`) with explicit
  per-project membership taking priority over an org-admin fallback, and
  workspaces nested under projects.
- **Authorization is enforced in the backend**, not just the Angular UI —
  every route depends on `require_org_member` / `require_org_admin` /
  `require_project_access`, which re-check membership against the database
  on every request. Cross-organization and cross-project access is rejected
  with 403/404, verified by `tests/test_organizations_and_projects.py`.
- **Audit log**: register/login, org/project create, member invite/role
  change/remove are recorded in `audit_logs`.

### Phase 2 — Real coding-agent connectivity
- **Common Agent Runtime Interface** (`app/services/agent_runtime/base.py`):
  the abstraction every coding-agent adapter implements — `capabilities()`
  and `health_check()`. Capability metadata carries an honest validation
  state (`declared` / `tested` / `verified`); only `verified` capabilities
  (currently: CLI detection) are exercised by the health check itself.
- **Adapters** (`app/services/agent_runtime/adapters.py`) for Claude Code,
  Codex, Gemini CLI and a generic Custom adapter. A **local-runtime** check
  shells out to the real CLI binary (`claude --version`, `codex --version`,
  `gemini --version`) on the backend host — if it's not installed, the
  result is honestly `not_connected`, never faked. A **factory-managed**
  check makes a real, minimal HTTPS call to the provider's own API
  (Anthropic / OpenAI / Gemini `models` endpoint) using the stored
  credential — a wrong or revoked key is reported as `not_connected` with
  the provider's actual rejection reason.
- **Credential broker** (`app/core/crypto.py`, `app/models/agent_runtime.py`
  `Credential`): org-scoped secrets, encrypted at rest with Fernet. The
  encrypted value — and the decrypted value — are never returned by any API
  response; only `has_credential: true/false` is exposed.
- **Coding-agent connection registry**: `GET /coding-agent-runtimes` (the
  static adapter catalog), and per-organization
  `GET/POST/DELETE /organizations/{id}/coding-agent-connections` +
  `POST .../{connection_id}/health-check`, enforced by the same
  `require_org_member` / `require_org_admin` dependencies as Phase 1.
  Verified in `tests/test_agent_runtimes.py`, including a non-mocked test
  that asserts a real local-runtime health check on this machine (which has
  no coding-agent CLI installed) honestly reports `not_connected`.

**On a machine with no `claude`/`codex`/`gemini` CLI installed and no
provider API key configured — true of the environment this was built in —
every runtime in the Settings UI correctly shows "Not configured" or "Not
connected," not a faked "Connected." Supplying a real CLI install or a real
provider API key makes the same code paths report a real "Connected."**

### Phase 3 — Task execution engine
- **Task model** (`app/models/task.py`): project-scoped tasks (`title`,
  `description`, `priority`, `status`, an optional
  `coding_agent_connection_id`), with a `not_started` → `running` →
  `completed`/`failed` lifecycle.
- **`start_execution`** added to the Common Agent Runtime Interface
  (`app/services/agent_runtime/base.py`) and every adapter. A local-runtime
  adapter shells out to the real CLI non-interactively (`claude -p`, `codex
  exec`, `gemini -p`); a factory-managed adapter makes a real chat-completion
  call to the provider's own API with the stored credential. Either path
  returns real output or a real error — never fabricated.
- **`app/services/task_execution.py`**: `POST
  /projects/{id}/tasks/{task_id}/start` re-runs the assigned connection's
  `health_check` immediately before execution (a cached "connected" status
  can go stale — CLI removed, key revoked), and only calls
  `start_execution` if that check currently passes. No connection assigned,
  a stale connection, or a failed runtime call all mark the task `failed`
  with the real reason; only an adapter that actually succeeded marks it
  `completed` with its actual output.
- Verified end-to-end in-browser against the real backend: a task with no
  connection assigned fails with "No coding-agent connection assigned to
  this task," and a task assigned to this machine's (CLI-less) Claude Code
  connection fails with "Claude Code is not connected: 'claude' CLI not
  found on PATH" — both are real responses from the real pipeline, not UI
  copy. 7 new backend tests (30/30 total), including a non-mocked one
  confirming this machine's honest failure path.
- The project workspace's **Tasks** tab (previously mock "Preview data") now
  creates, lists, and starts real tasks against real connections.

## What's intentionally not here yet

The Factory Supervisor's multi-step orchestration, streaming a running
agent's output live (execution is currently synchronous, bounded by a
request timeout), Temporal/LangGraph workflow orchestration, the Neo4j
knowledge graph, Docker execution isolation, and real-time collaboration
are later phases of the execution spec and are not implemented in this
pass.

## Running locally

```bash
docker compose up -d postgres   # from the repo root; exposes Postgres on localhost:5433
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
cp .env.example .env                            # edit SF_DATABASE_URL etc. if needed
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8010
```

The frontend (`frontend/src/environments/environment.ts`) points at
`http://localhost:8010/api/v1` in development.

## Running tests

Tests run against the same Postgres database (`software_factory`) and clean
up their own rows after each test:

```bash
.venv/Scripts/python -m pytest -q
```

## Running the full stack in Docker

See the [root README](../README.md) — `docker compose up -d --build` from
the repo root starts Postgres, this backend, and the Angular frontend
together.
