# Software Factory — Backend (Phases 1–18: Foundation Through Branch Protection Visibility)

FastAPI + PostgreSQL (+ Neo4j) backend implementing real authentication,
organizations, membership, RBAC, projects, workspaces, coding-agent runtime
connectivity, real-time streaming task execution, the Factory Supervisor's
multi-step workflow orchestration, real-time multi-user presence/
collaboration, a real Neo4j-backed knowledge graph of each project's
actual work, genuine Docker-isolated task execution, real repository
source-code parsing into that knowledge graph, and a dashboard built
entirely from real, access-scoped aggregate queries — the foundation
the rest of the Software Factory execution spec (Temporal/LangGraph
orchestration, etc.) builds on.

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

### Phase 7 — Real Neo4j-backed knowledge graph
- **This is a graph of what the factory actually did, not a parsed-code
  graph**: there is no repository-ingestion pipeline yet (`repository_url`
  is still just a string field), so rather than fabricate "37,892
  entities" of code analysis that doesn't exist, this phase builds a
  genuinely real graph from the data this backend already owns —
  projects, tasks, workflows, coding-agent connections, and the users who
  created them — with real relationships (`HAS_TASK`, `HAS_WORKFLOW`,
  `HAS_STEP`, `ASSIGNED_TO`, `CREATED`).
- **`app/services/knowledge_graph.py`**: `health_check()` makes a real
  `RETURN 1` call to Neo4j and reports the real driver error if it's
  unreachable — this is checked before every sync and every graph read,
  never assumed. `sync_project()` reads a project's real rows from
  Postgres and `MERGE`s them into Neo4j (idempotent — syncing twice never
  duplicates nodes or relationships). `get_project_graph()` reads the
  real graph straight back out via Cypher.
- **Routes** (`app/api/routes/knowledge.py`): `POST
  /projects/{id}/knowledge/sync` and `GET /projects/{id}/knowledge/graph`,
  both behind the same `require_project_access` RBAC check as every other
  project resource. Either one honestly returns `connected: false` with
  Neo4j's real error if the graph database isn't reachable — never a
  fabricated success or a silently-empty-but-"OK" graph.
- A dedicated `neo4j` service was added to `docker-compose.yml` (host
  ports 7475/7688, so it doesn't collide with any other local project's
  Neo4j instance) — this project's own graph database, not a shared one.
- Verified end-to-end against a real, running Neo4j container: syncing a
  project with a real task (assigned to a real connection), a real
  two-step workflow, and their real creator produced exactly 7 real nodes
  and 11 real relationships (confirmed via the raw sync and graph
  response bodies), and the project workspace's **Knowledge** tab
  (previously a static sentence pointing at an unrelated mock explorer)
  now renders that real graph with a working "Sync now" control. 4 new
  backend tests (51/51 total) run against this project's actual Neo4j
  instance, including a real sync-then-query round trip and an
  idempotency check, and skip honestly (rather than fail) if Neo4j isn't
  reachable in a given test environment.

### Phase 8 — Docker execution isolation
- **A new `DockerSandboxAdapter`** (`app/services/agent_runtime/adapters.py`)
  implements the same Common Agent Runtime Interface as every other
  adapter, but instead of talking to a hosted coding-agent provider it
  runs a task's prompt as a shell command inside a container via the
  host's real `docker` CLI: `docker run --rm --network none --memory
  256m --cpus 0.5 python:3.11-slim sh -c "<prompt>"`. `--network none`
  means the container has no network stack at all (not just a firewall
  rule), and `--memory`/`--cpus` are real limits enforced by the Docker
  daemon itself, not documentation.
- **`health_check()`** shells out to `docker version` on the backend
  host; if the daemon isn't reachable (or the CLI isn't installed), it
  honestly reports `not_connected` with the real error — exactly like
  every other adapter's honest-failure path. On this development
  machine, Docker Desktop's daemon genuinely is reachable, which makes
  this **the first adapter in the whole project whose health check and
  task execution can both genuinely succeed** here, rather than only
  exercising the honest-failure path.
- **`start_execution()`/`start_execution_streaming()`** reuse the exact
  same `subprocess.Popen` line-by-line streaming and `proc.terminate()`
  cancellation pattern established in Phase 4 — a cancelled sandboxed
  task really kills the `docker run` client and the container it
  started, not just a flag.
- Verified with real, non-mocked tests (`tests/test_docker_sandbox.py`):
  a real command's stdout comes back out of a real container; a DNS
  lookup from inside the container genuinely fails with
  `socket.gaierror`/"Temporary failure in name resolution", proving
  `--network none` is real isolation and not just a label; a non-zero
  exit code is reported as a genuine failure; a full task run against a
  real `docker_sandbox` connection reaches `status: "completed"` with
  real output (`real-sandbox-output`); and a genuine cancellation mid
  -`sleep 30` returns in well under the full sleep window, proving the
  container was actually killed rather than left running. 6 new backend
  tests (57/57 total) — they skip honestly (never fail) if no Docker
  daemon is reachable in a given test/CI environment.
- Verified end-to-end in-browser against the real backend: the Settings
  page lists "Docker Sandbox" automatically (same dynamic adapter-
  registry catalog as every other runtime, zero frontend changes),
  clicking Connect produces a real `"status": "connected"`,
  `"detected_version": "28.5.1"` response from a real `docker version`
  call, and a task created against that connection and started from the
  browser reaches `"status": "completed"` with real output
  `"real-sandbox-output\n"` and an empty `error_message` — confirmed via
  the raw network responses, not UI copy.

### Phase 9 — Real repository code ingestion into the knowledge graph
- **`app/services/code_ingestion.py`**: walks a real directory on the
  backend host and parses real source files — Python with the real `ast`
  module (genuine function/class definitions with real line numbers),
  TypeScript/JavaScript with a lightweight top-level-declaration regex
  scan (clearly scoped as a declaration scan, not a full compiler, so it
  can miss unusual syntax but never reports a symbol that isn't really
  there). `node_modules`, `.git`, `.venv`, build output, etc. are
  skipped; a nonexistent or non-directory path raises a real error
  rather than returning a silently-empty "success."
- **Deliberately local-path only, no remote-git-URL variant**: cloning an
  arbitrary URL server-side would turn this endpoint into an
  SSRF/arbitrary-fetch vector. Ingestion only ever reads a directory the
  backend process can already see — a real constraint, documented in
  the API and the UI, not a missing feature.
- **`knowledge_graph.ingest_repository()`**: before writing, it deletes
  this project's *previous* File/Function/Class subgraph, so a file or
  symbol that genuinely no longer exists on disk doesn't linger as a
  stale node after re-ingestion — then `MERGE`s the current, real
  disk state in. `get_code_graph()` reads it straight back out.
- **Routes** (`app/api/routes/knowledge.py`): `POST
  /projects/{id}/knowledge/ingest-repository` (restricted to
  `project_admin` — this is an elevated operation, since it reads
  whatever filesystem path the backend can see, not a read-only one) and
  `GET /projects/{id}/knowledge/code-graph`.
- Verified end-to-end in-browser against the real backend: ingesting
  this very repository's own `app/services/agent_runtime/` directory
  returned `files_scanned: 4`, `symbols_found: 51` (confirmed via the
  raw response body), and the Knowledge tab's new "Repository Code
  Structure" card rendered the real file list with every real function
  and class — including `DockerSandboxAdapter` from Phase 8 — at its
  real line number. 7 new backend tests (62/62 total): real symbol
  parsing from a `tmp_path` fixture, a real "path doesn't exist" error,
  a real Neo4j round trip, and a real 403 for a non-admin project
  member.

### Phase 10 — A real dashboard
- **The previous dashboard's stat cards, "Recent Activity," "Running
  Workflows," and "System Health" panels were all static mock data**
  (`MockDataService`) — the project list beside them was already real,
  which made the page an inconsistent mix of real and fabricated
  content. This phase replaces every one of those panels with a real,
  access-scoped aggregate.
- **`app/services/dashboard.py`**: `get_summary(db, user)` computes real
  `COUNT()`-equivalent totals (organizations, projects, tasks,
  workflows, configured connections) over exactly the organizations and
  projects this user can actually access — `_visible_project_ids()`
  mirrors the same explicit-membership-or-org-admin rule enforced by
  `require_project_access` elsewhere, not "every row in the database."
  A user with no access to anything gets a genuinely empty dashboard,
  not another user's numbers.
- **No fabricated ETA**: a running workflow's progress is `current_step
  / total_steps` from real rows, and its displayed duration is a real
  `now - started_at` elapsed time — there is no invented "~4 min
  remaining" estimate, which this codebase has no honest way to
  compute.
- **Real system health, not a static "All Services Operational"
  banner**: each dependency (Postgres, Neo4j) is checked with a real
  query (`SELECT 1`, and the same `knowledge_graph.health_check()` used
  by Phase 7) at request time, and the banner only claims "reachable"
  when every check actually passed.
- **Route**: `GET /dashboard/summary`, authenticated but with no
  project/org path parameter — it computes its own visibility scope
  per-user rather than trusting a caller-supplied ID.
- 4 new backend tests (66/66 total): real counts scoped correctly for
  one user and genuinely zero for another user with no access, real
  workflow progress/elapsed-time math (driven via a direct DB fixture
  to avoid racing the Factory Supervisor's background thread rather
  than asserting on a flaky timing window), real dependency health, and
  a real 401 for an unauthenticated request.
- Verified end-to-end in-browser against the real backend: a fresh
  user/org/project/task/workflow created via the real API produced
  `tasks_total: 3` (1 standalone task + the 2 real Task rows that are a
  workflow's steps — confirmed via the raw response body), real recent-
  activity entries in the real order they happened, and both dependency
  checks reporting `connected: true`.

### Phase 11 — A real global "My Tasks" view
- **The global `/tasks` page was the last major holdout of fabricated
  UI**: it rendered a hardcoded `TSK-4827` demo task with an invented
  multi-agent chat, a fake "Execution Plan," a fake "Task Breakdown
  (Agents)" panel, and fake file/PRD references — entirely disconnected
  from the real `Task` model every other task-facing surface in this
  app (the project workspace's Tasks tab, task start/cancel/stream) has
  used since Phase 3. This phase removes that fabricated page and
  replaces it with a real one, rather than inventing backend features
  (per-task chat threads, multi-agent breakdown, file diffs) that
  nothing else in this codebase has asked for or could honestly back.
- **`app/services/access.py`**: `visible_project_ids(db, user)` — the
  same explicit-membership-or-org-admin visibility rule
  `require_project_access` enforces per-request, factored out so it can
  be computed once for a whole cross-project view. `app/services/
  dashboard.py` (Phase 10) now calls this shared helper instead of its
  own private copy.
- **`GET /tasks/mine`**: every real task across every project this user
  actually belongs to, each annotated with its real project name. A
  user with access to nothing gets a genuinely empty list.
- The rebuilt task-workspace page shows only what's real: title,
  description, priority, status, real timestamps, and the task's real
  `output`/`error_message` — with working Start/Cancel buttons wired to
  the same real execution pipeline as every other task surface.
- 3 new backend tests (69/69 total): real cross-project aggregation,
  a genuinely empty list for a user with no access, and a real 401 for
  an unauthenticated request.
- Verified end-to-end in-browser against the real backend: a user with
  tasks in two different projects saw both, correctly labeled with
  their real project names; starting a task with no coding-agent
  connection assigned produced a real `"status": "failed"` with the
  real error `"No coding-agent connection assigned to this task."`,
  rendered live in the UI via the existing real SSE stream — not a
  fabricated multi-agent transcript.

### Phase 12 — A real global Workflow view
- **The global `/workflows` page was the same kind of fabrication Phase
  11 removed from `/tasks`**: a hardcoded workflow with an invented DAG
  canvas (draggable nodes at fake x/y coordinates), a fake streaming
  "Live Log," and a fake artifacts list — none of it backed by the real
  `Workflow`/`Task` models every other workflow surface (the project
  workspace's Workflows tab, start/cancel/stream) has used since Phase
  5. Workflows in this codebase are a real **linear ordered sequence of
  steps**, not a DAG, so a DAG visualization would misrepresent the
  real model even if it were wired to real data — this phase replaces
  it with a real step-sequence view instead.
- **`GET /workflows/mine`**: every real workflow across every project
  this user belongs to, reusing Phase 11's `visible_project_ids()`
  helper, each annotated with its real project name and its real
  ordered step list (already modeled as real `Task` rows since Phase
  5).
- The rebuilt workflow-detail page shows the real step list with each
  step's real status and real output/error, real progress (`current_step
  / total steps`), and real timestamps — with working Start/Cancel wired
  to the same Factory Supervisor pipeline as the project workspace's
  Workflows tab.
- **Fixed a route gap found while building this**: `/workflows/:id` had
  no route registered at all (only the bare `/workflows` did), so
  clicking into a specific workflow silently fell through to the
  dashboard. Added the missing route.
- 3 new backend tests (72/72 total): real cross-project aggregation
  with real step lists, a genuinely empty list for a user with no
  access, and a real 401.
- Verified end-to-end in-browser against the real backend: a user with
  workflows in two different projects saw both with correct project
  names; a started workflow with no connection assigned showed its real
  first step `failed` with the real error, and its later steps
  honestly `not_started` — never fabricated as having run.

### Phase 13 — Git connectivity & synchronization
- **A provider-independent `GitProviderAdapter` interface**, mirroring
  the `CodingAgentRuntimeAdapter` pattern from Phase 2 exactly, so
  adding GitLab/Bitbucket later never requires touching routes or
  orchestration code. `GitHubAppAdapter` is the only implementation so
  far, authenticating as a real GitHub App: a real RS256 JWT signed with
  the platform's App private key, exchanged for a real short-lived
  installation access token via GitHub's `/app/installations/{id}/access_tokens`
  API — never a long-lived personal access token.
- **Honest failure, identical to Phase 2's pattern**: if
  `SF_GITHUB_APP_ID`/`SF_GITHUB_APP_PRIVATE_KEY` aren't configured on
  this backend, every installation, health check, and repository
  discovery call honestly reports "not connected" / a real
  `GitProviderError` with the actual reason — never a simulated
  success.
- **New models**: `GitInstallation` (one real GitHub App installation
  per organization), `RepositoryConnection` (one real repository mapped
  to a project, created only from installations the project's own
  organization owns), and `WebhookEvent` (every inbound webhook
  delivery, signature-verified and idempotency-checked before being
  trusted).
- **Real webhook receiver** at `POST /api/v1/webhooks/github`: verifies
  `X-Hub-Signature-256` with `hmac.compare_digest` against
  `SF_GITHUB_WEBHOOK_SECRET` (an unverifiable signature is rejected
  with 401 and recorded, never processed), and is idempotent on
  `(provider, provider_delivery_id)` — a redelivered event is recognized
  and returned without reprocessing. `push` events sync the matching
  repository connection's real latest commit SHA; other event types are
  still recorded, honestly tagged "not yet implemented" rather than
  silently dropped or faked as handled — their deeper handling (PR
  lifecycle, CI status, branch protection) is later roadmap scope.
- **Manual "Sync now"** (`POST /projects/{id}/repository-connections/{id}/sync`)
  reruns the same real sync logic a webhook triggers, the recovery path
  the spec requires for when a webhook delivery is missed.
- RBAC: creating/revoking an org's GitHub App installation requires org
  admin; connecting a repository to a project requires project admin;
  an installation can only back a repository connection for a project
  in the installation's own organization (cross-org use is a 404, not a
  silent success).
- Frontend: a real "Git Installations" panel under Settings → Tools &
  Integrations (org-scoped, mirrors the Coding Agent Connections panel),
  and a real "Repository Connections" panel under each project's
  Settings tab — connecting a repository lists the installation's
  actually-discovered GitHub repositories, never a typed-in guess.
- 14 new backend tests (86/86 total): a genuine RS256 JWT round-trip
  against a throwaway keypair, real HMAC signature verification (valid/
  tampered/wrong-secret/missing), the honest not-configured path
  through the real API (no GitHub App configured on this dev machine),
  RBAC and cross-org isolation, repository-connection creation and
  manual-sync recovery (network edge stubbed, decision logic real),
  and webhook idempotency/signature-rejection/push-sync.
- Verified end-to-end in-browser against the real backend: connecting
  an installation with no GitHub App configured showed the real
  "GitHub App not configured on this backend" error inline, both in the
  org-level installation list and when attempting to list a project's
  connectable repositories — never a fabricated repository list.

### Phase 14 — Task-specific Git worktrees & real execution
- When a task's project has a connected repository (Phase 13), starting
  the task now clones that real repository (using a real, short-lived
  GitHub App installation token) into an isolated directory dedicated to
  that task, checks out a new real branch (`sf-task-<id>`), and runs the
  task against that checkout — not a bare prompt with no codebase. A
  project with no repository connection behaves exactly as before: no
  worktree, same bare-prompt execution Phases 2-13 always had.
- **Real adapters, not a simulated filesystem**: the Common Agent Runtime
  Interface's `start_execution`/`start_execution_streaming` gained an
  optional `cwd` parameter. A local-CLI adapter (Claude Code, Codex,
  Gemini CLI, Qwen) runs the real CLI with that directory as its working
  directory, so whatever files it genuinely edits land in the real
  worktree. Docker Sandbox bind-mounts the worktree into the container at
  `/workspace`. A hosted-API adapter (credential mode) or the Custom
  adapter has no local filesystem to run in and honestly ignores `cwd`
  rather than pretending to use it.
- **Real diff capture, never fabricated**: after the adapter run finishes
  (success or failure), the backend stages every real change inside the
  worktree (`git add -A`), and — only if something actually changed —
  commits it on the task's branch and records the genuine `git diff`
  output and real changed-file list on the task row. A run that touched
  no files leaves both empty, never a synthesized diff.
- **Honest failure, identical pattern to every other integration point**:
  if the clone, checkout, or diff collection fails for any real reason
  (provider auth, network, a `git` error), the task is marked `failed`
  with that real reason — it never silently falls back to a bare prompt
  with no worktree, and it never reports a fabricated success.
- New `GET /projects/{id}/tasks/{id}/diff` endpoint returns the real
  branch name, base branch, changed-file list and diff text; the SSE
  stream and task list/detail responses carry the branch name and
  changed-file count live as the run progresses.
- 8 new backend tests (95/95 total): real local-repository clone/branch/
  commit/diff round trips (only the provider's clone-URL network edge is
  stubbed, exactly like Phase 13's pattern), the empty-diff case, a
  worktree-preparation failure honestly failing the task, and a full
  API-level test that starts a task, verifies the real branch/diff via
  both the task response and the new diff endpoint.
- Verified end-to-end in-browser against the real backend: connected a
  real GitHub repository (`fintrix`) through the real installed GitHub
  App, ran a task against it through both the real Claude Code CLI (which
  honestly failed with a real, unrelated local OAuth-expiry error — the
  worktree itself cloned and branched correctly) and the Docker Sandbox
  runtime (which genuinely wrote a file inside the real bind-mounted
  worktree, completed, and produced a real diff visible in both the
  project workspace's Tasks tab and the global My Tasks page). This pass
  also caught and fixed two genuine, non-obvious bugs surfaced by that
  real run rather than a mock: a relative worktree path that Docker's
  volume-mount flag rejects outright (fixed by always resolving the
  worktree root to an absolute path), and Windows leaving read-only `git`
  pack files behind after a plain `shutil.rmtree`, which broke re-running
  a task whose previous worktree directory still partially existed (fixed
  with an `onerror` handler that clears the read-only bit before retrying
  the removal).

### Phase 15 — Opening a real pull request from a task's branch
- Once a task with a connected repository actually changes a file (real,
  non-empty `git diff` from Phase 14), the backend pushes its real branch
  to the real remote (`git push origin sf-task-<id>`, authenticated with
  the same short-lived installation credential the clone used) and opens
  a real pull request from it via the Git Provider Interface's new
  `create_pull_request` method — a genuine GitHub API call
  (`POST /repos/{owner}/{name}/pulls`), never a fabricated PR number or
  URL. A task with no changes, or no repository connection, opens no PR,
  exactly as before this phase.
- **Honest failure, same pattern as every other integration point in this
  phase**: a push or PR-creation failure (an expired credential, a branch
  protection rule, an already-open PR for that branch) is recorded as a
  real, specific note on the task's `error_message` — it never overturns
  the coding agent's own success/failure verdict, and it never fabricates
  a PR number or URL on failure.
- The task row gained `git_pr_url`/`git_pr_number`, surfaced in the task
  response, the SSE stream, and a "PR #N" link in both the project
  workspace's Tasks tab and the global task workspace's Git sidebar card.
- 7 new backend tests (102/102 total): a real `git push` against a local
  repository standing in for the remote (plus a credential-redaction test
  for a real push failure), `create_pull_request`'s honest not-configured
  path, a direct test of the real GitHub API request/response handling
  (only `httpx.post` stubbed — JWT minting, request construction and
  response parsing are the genuine adapter code), an honest-rejection
  case, and two full task-execution tests (a real push + PR open with the
  PR fields verified on the task response, and a PR-creation failure that
  is reported without overturning the task's own `completed` status).

### Phase 16 — Real pull-request lifecycle via GitHub's own webhook
- A task's `git_pr_state` ("open", "closed", or "merged") is no longer
  just the value Phase 15 recorded at PR-creation time — it's kept in
  sync with the PR's real lifecycle by GitHub's own `pull_request`
  webhook event, which Phase 13 already received and recorded but didn't
  yet act on. Matching is by real PR number within the connected
  project only — never guessed from branch name or timing, and a
  `pull_request` event for a PR this backend didn't open (or for a
  project it can't match) is recorded honestly as such, never silently
  dropped or treated as an error.
- `state` is derived the same way GitHub itself represents it: `merged`
  when the payload's `pull_request.merged` is true, otherwise GitHub's
  own `open`/`closed` — never inferred from the webhook `action` field.
- The PR state is surfaced as a pill next to the "PR #N" link in both the
  project workspace's Tasks tab and the task workspace's Git sidebar
  card.
- 2 new backend tests (104/104 total): a real webhook delivery that
  flips a matching task's PR state to `merged` (verified by re-fetching
  the task over the API), and a `pull_request` event that matches no
  task, recorded honestly rather than silently accepted or errored.

### Phase 17 — Real CI status via GitHub's own check-suite webhook
- A task's `git_ci_status` is the real, live CI result for its branch —
  never run or simulated by this backend. It's kept in sync by GitHub's
  own `check_suite` webhook event (received and recorded since Phase 13,
  not yet acted on until now): the real in-progress `status`
  (`queued`/`in_progress`) before GitHub's check suite completes, then
  its real `conclusion` (`success`/`failure`/...) once it does.
- Matched by the real head branch within the connected project only —
  never guessed from timing or task state. A `check_suite` event for a
  branch this backend didn't create (or for a project it can't match) is
  recorded honestly as such, never silently dropped or treated as an
  error.
- Surfaced as a "CI: <status>" pill in the project workspace's Tasks tab
  and a "CI" row in the task workspace's Git sidebar card.
- 3 new backend tests (107/107 total): a completed check suite flipping
  a matching task's CI status to its real conclusion, an in-progress
  suite reporting its real `status` rather than a fabricated conclusion,
  and a check-suite event matching no task recorded honestly rather than
  silently accepted or errored.

### Phase 18 — Branch protection rules, surfaced (not enforced)
- Right after a task's pull request is opened, this backend asks GitHub
  for the base branch's real branch protection rules via a new
  `get_branch_protection` method on the Git Provider Interface
  (`GET /repos/{owner}/{name}/branches/{branch}/protection`) and records
  them on the task: whether the branch is protected at all, the real
  required status check contexts, and the real required approving
  review count. An unprotected branch (`404` from GitHub) is a real,
  successful result, not an error.
- Informational only — this backend never enforces or bypasses these
  rules itself; GitHub's own merge button is what actually requires
  them. A lookup failure never overturns the PR that was already opened
  successfully; it's appended to the task's `error_message` honestly.
- Surfaced as a "protected" pill (with required checks/reviews as a
  tooltip) next to the PR link in the project workspace's Tasks tab, and
  a "Branch protection" row in the task workspace's Git sidebar card.
- 7 new backend tests (113/113 total): an unprotected branch reported
  honestly, a protected branch's real required checks/review count
  parsed correctly, the adapter failing honestly without a configured
  GitHub App, an unexpected GitHub error raised honestly, a task's PR
  recording the real protection rules end to end, and a protection
  lookup failure reported without overturning the task's own success.

## What's intentionally not here yet

Temporal/LangGraph-based durable workflow orchestration (this pass's
Factory Supervisor sequences steps via a background thread against the
real database, not a distributed workflow engine), cloning a remote git
repository server-side for ingestion (by design — see Phase 9; ingestion
only reads a local path the backend host can already see), actually
enforcing branch protection rules (Phase 18 reads and surfaces them;
GitHub's own merge button is what enforces them, by design — this
backend doesn't merge PRs), and coordinating presence across multiple
backend replicas (Phase 6's presence registry is single-process/
in-memory) are later phases of the execution spec and are not
implemented in this pass.

Several frontend-only pages the original UI scaffold shipped with are
still backed by static mock data rather than this backend — Agents,
Prompts, Artifacts, Approvals, Monitoring, Providers, Repository
Intelligence, and Code Review. (Dashboard, the global Task view, the
global Workflow view, and the project workspace's Tasks/Workflows/
Knowledge tabs are all real — see Phases 3–12.) Each of those remaining
pages implies backend features this spec hasn't asked for yet (per-task
chat threads, file diffs, approval workflows, log aggregation); they're
listed here
rather than quietly left inconsistent with the rest of the app.

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
