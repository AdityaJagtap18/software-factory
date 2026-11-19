# Software Factory — Backend (Phases 1–6: Foundation Through Live Collaboration)

FastAPI + PostgreSQL backend implementing real authentication, organizations,
membership, RBAC, projects, workspaces, coding-agent runtime connectivity,
real-time streaming task execution, the Factory Supervisor's multi-step
workflow orchestration, and real-time multi-user presence/collaboration —
the foundation the rest of the Software Factory execution spec
(Temporal/LangGraph orchestration, knowledge graph, etc.) builds on.

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

### Phase 4 — Real-time streaming execution
- `POST /projects/{id}/tasks/{task_id}/start` now returns immediately with
  `status: "running"` and runs the adapter call in a background thread
  (`app/services/task_execution.py`, `start_task_in_background`) instead of
  blocking the request.
- **`start_execution_streaming`** added to the Common Agent Runtime
  Interface. Local-runtime adapters use `subprocess.Popen` and emit each
  real stdout line as it's produced; factory-managed adapters use each
  provider's actual SSE streaming endpoint (`"stream": true` for
  Anthropic/OpenAI, `alt=sse` for Gemini) and emit each genuine token delta.
  Every chunk is appended to the task's `output` in the database as it
  arrives — nothing is buffered and released all at once to fake
  "streaming."
- **`POST .../tasks/{task_id}/cancel`**: sets a `cancel_requested` flag;
  the running adapter call checks it between real chunks (next CLI output
  line / next SSE delta) and stops there — a local CLI's child process is
  terminated, an HTTP stream is closed — recording whatever partial output
  was genuinely produced plus `"Cancelled by user."`, never a fabricated
  "cancelled instantly" state.
- **`GET .../tasks/{task_id}/stream`**: Server-Sent Events, polling the
  real task row every 0.5s and forwarding its actual `status`/`output`/
  `error_message` until the task reaches a terminal state. The frontend
  reads this directly (`fetch` + a manual SSE line parser, since the
  `EventSource` API can't carry the `Authorization` bearer header this API
  requires) instead of polling.
- Verified end-to-end in-browser: `POST .../start` returns `"running"`
  immediately (confirmed via the raw network response), the Tasks tab
  updates live from the SSE stream with no manual refresh, and a slow
  mocked execution responds to a real `cancel` call mid-run. 3 new backend
  tests (33/33 total), including one asserting the real `cancel_requested`
  flag actually stops a streaming mock with the correct partial output, and
  one reading real SSE bytes off the stream endpoint.

### Phase 5 — Factory Supervisor multi-step orchestration
- **Workflow model** (`app/models/workflow.py`): project-scoped, with a
  `not_started` → `running` → `completed`/`failed` lifecycle, a
  `current_step_index`, and a `cancel_requested` flag — the same shape as
  `Task`. Each workflow's ordered steps **are** `Task` rows (new nullable
  `workflow_id` + `step_order` columns on `Task`), so every step reuses the
  exact same execution pipeline as a standalone task — health-check,
  real streaming execution, cancellation — with no second, parallel
  execution path to keep honest.
- **`app/services/task_execution.py`** was refactored to expose
  `execute_task(db, task, extra_should_cancel=None)`, the per-task
  execution core (previously inlined in `_run`), so it can be called
  directly — within the same DB session/thread — once per step, instead
  of only from its own standalone background thread.
- **`app/services/workflow_execution.py`** (the Factory Supervisor): runs a
  workflow's steps in order in a single background thread. It checks
  `workflow.cancel_requested` before starting each step and threads an
  `extra_should_cancel` closure into the currently-running step so a
  workflow-level cancel also interrupts it at its next real chunk boundary
  — never a fabricated instant stop. The **first step that genuinely
  fails halts the whole workflow**: it is marked `failed` and every later
  step is left `not_started` — never run, and never reported as
  succeeded. A workflow only reaches `completed` once every one of its
  steps has genuinely completed.
- **Routes** (`app/api/routes/workflows.py`): `POST/GET
  /projects/{id}/workflows`, `GET/DELETE .../workflows/{workflow_id}`,
  `POST .../start` (non-blocking, mirrors task start), `POST .../cancel`,
  and `GET .../stream` (SSE: real workflow + per-step status/output polled
  from the database, exactly like the task stream).
- Verified end-to-end in-browser against the real backend: creating a
  two-step workflow with no coding-agent connection assigned, then
  starting it, produces (confirmed via the raw SSE bytes on the network
  tab) a real `"status": "failed"` with step one's actual error —
  `"No coding-agent connection assigned to this task."` — and step two
  honestly left `"status": "not_started"`, never started. 10 new backend
  tests (43/43 total), including a non-mocked one confirming this
  machine's honest step failure, a mocked all-steps-succeed test, a
  mocked "step 2 never runs after step 1 fails" test, a workflow-cancel
  test, an SSE-stream-reading test, and a cascade-delete test.
- The project workspace's **Workflows** tab (previously mock "Preview
  data") now creates (with an ordered, addable/removable step list, each
  optionally assigned a connection), lists, starts, and cancels real
  workflows, with live per-step progress chips driven by the same
  fetch+SSE pattern as the Tasks tab.

### Phase 6 — Real-time multi-user collaboration
- **Live project presence** (`app/services/presence.py`,
  `app/api/routes/presence.py`): a `WebSocket` endpoint,
  `GET /projects/{id}/presence/ws`, backed by an in-memory, per-process
  connection registry. A viewer appears the instant their socket connects
  (after a real JWT + project-membership check — a browser `WebSocket`
  can't send an `Authorization` header, so the access token travels as a
  query parameter, verified exactly like `get_current_user`) and
  disappears the instant it closes — tab closed, navigation away, network
  drop. Every join or leave triggers a real server-pushed broadcast of
  the current viewer list to every other open socket on that project —
  not a per-client poll or a locally-estimated count. Honestly scoped:
  this coordinates presence within a single backend process, not across
  multiple replicas (that would need a shared pub/sub this pass doesn't
  add).
- **Shared live task/workflow progress**: previously, only the browser
  tab that actually clicked "Start" ever attached to a task's or
  workflow's SSE stream, so a second viewer of the same project wouldn't
  see progress update until they manually refreshed. `TaskService` and
  `WorkflowService` (frontend) now also attach the live stream for any
  task/workflow that is already `running` when a viewer's page loads —
  every viewer watching real progress, not just the one who started it.
- Verified end-to-end with two real logged-in users and two real
  WebSocket connections: opening the same project in a second session
  live-pushed an updated viewer count to the first session with no
  refresh (confirmed via the raw presence payload), and a task flipped to
  `running` was picked up live by a browser tab that never clicked Start
  (confirmed by its automatic `GET .../tasks/{id}/stream` request). 4 new
  backend tests (47/47 total) exercise the WebSocket directly — invalid
  token, no project access, a single viewer seeing themselves join, and a
  second real socket triggering a genuine broadcast to the first.

## What's intentionally not here yet

Temporal/LangGraph-based durable workflow orchestration (this pass's
Factory Supervisor sequences steps via a background thread against the
real database, not a distributed workflow engine), the Neo4j knowledge
graph, Docker execution isolation, and coordinating presence across
multiple backend replicas (this pass's presence registry is single-
process/in-memory) are later phases of the execution spec and are not
implemented in this pass.

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
