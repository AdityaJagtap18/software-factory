# Agent Orchestration & Provider Integration Audit (Sections B & C)

Scope: `backend/app/services/agent_runtime/`, `backend/app/services/task_execution.py`,
`backend/app/services/workflow_execution.py`, `backend/app/models/agent_runtime.py`,
`backend/app/models/task.py`, `backend/app/models/workflow.py`, `backend/app/api/routes/agent_runtimes.py`,
compared against the intended architecture in `Software_Factory_Architecture_Decision_Log (1).md`
("Domain 2 — Multi-Agent Orchestration", §4, and "Decision 1 — Unified Agent Runtime" / "Decision 3 —
Coding-agent execution and integration", §1194+).

Method: every claim below is backed by a specific file/line/class read directly from source. Where the
decision log describes an intended design and the codebase has no matching implementation, this is stated
as NOT IMPLEMENTED rather than inferred as "partially done."

---

## A. Intended architecture (from the decision log) — baseline for comparison

The decision log specifies, among others:
- A central Supervisor + Planner + specialized Agent Workers (Product/Architect/Backend/Frontend/QA/DevOps),
  §362–470, with an **Agent Registry** (agent ID/version, capabilities, status) — §802–824.
- **Controlled agent communication** via shared workflow state + task contracts, not free agent-to-agent
  chat — §461–503.
- **Hybrid task decomposition** (supervisor-planned DAG + agent-proposed tasks validated by supervisor) —
  §605–762.
- **Agent assignment** via a filtered/ranked registry match, with escalation if no eligible agent exists —
  §775–824.
- **Policy-controlled provider routing/fallback**, model version pinning, provider comparisons segmented
  by agent role — §886–944, §1365–1389.
- **One common Agent Runtime Interface with two specialized families**: LLM adapters and coding-agent
  adapters (Decision 1, §1194–1227; PI-01/PI-02 at §1311–1312).
- **Docker isolation per coding execution attempt**, external Git-state/checkpoint preservation, native
  session resume as an optimization only, versioned handover packages (Decision 3, §1227–1240).
- QA/review as a separate responsibility from the implementing agent; agents never write directly to
  protected branches (§1623–1625).

None of this Supervisor/Planner/Agent-Registry/worker-pool/task-contract architecture exists in the
repository. What exists is a single-adapter, single-prompt task runner. Each feature below is scored
against what the decision log actually promises.

---

## B. Agent Management & Orchestration

### B1. Agent registration / configuration
**Status: PARTIALLY IMPLEMENTED (as "connection", not "agent").**
There is no Agent entity at all. `backend/app/models/agent_runtime.py` defines only:
- `Credential` (org-scoped secret) and
- `CodingAgentConnection` (an org's single configured instance of a runtime adapter, unique per
  `(organization_id, runtime_slug)` — `UniqueConstraint("organization_id", "runtime_slug", name="uq_org_runtime")`).

This is provider/runtime *connection* configuration (API key or local CLI), not agent registration —
there is no agent ID, version, role, specialization, or multiple-instances-per-runtime concept. The decision
log's "Agent Registry" (agent ID/version/capabilities/status, §802–824) is NOT IMPLEMENTED.

### B2. Agent roles / capability schema
**Status: MOCKED-HARDCODED (flat list, not hierarchical).**
`backend/app/services/agent_runtime/base.py` defines `Capability(name: str, state: CapabilityState)` where
`CapabilityState` is an honesty-graded enum (`DECLARED` / `TESTED` / `VERIFIED`, lines 17–28). Each adapter's
`capabilities()` method (e.g. `ClaudeCodeAdapter.capabilities()`, `adapters.py:530-536`) returns a flat,
hand-written list such as `Capability("Start session", CapabilityState.DECLARED)`. This is a static,
per-adapter capability *label* list, not the decision log's hierarchical capability schema tied to an agent
role taxonomy (Product/Architect/Backend/Frontend/QA/DevOps). There is no "role" field anywhere in the
models. Exposed via `_capability_schemas()` in `backend/app/api/routes/agent_runtimes.py:24-26` purely for
UI display.

### B3. Agent assignment
**Status: IMPLEMENTED BUT NOT VERIFIED (trivial single-FK assignment, not registry-based).**
`Task.coding_agent_connection_id` (`backend/app/models/task.py:47-51`) is a plain FK to one
`CodingAgentConnection`. There is no eligibility filtering, ranking, or escalation-when-unavailable logic —
`task_execution.execute_task()` (`task_execution.py:60-99`) just does `db.get(CodingAgentConnection, …)` and
fails the task outright if null or not connected. No registry query, no "no eligible agent" escalation path
exists (contradicts §823–824's "task waits or is escalated" requirement).

### B4. Agent execution
**Status: IMPLEMENTED AND VERIFIED (for the single-prompt case).**
`execute_task()` in `backend/app/services/task_execution.py:60-209` genuinely: looks up the connection,
decrypts the credential (`decrypt_value`), re-checks `adapter.health_check()` right before running (line 93,
explicitly to avoid a stale cached status), and calls
`adapter.start_execution_streaming(task.description or task.title, credential_value, on_chunk, should_cancel, cwd=worktree.path if worktree else None)`.
Streaming output is persisted to `task.output` incrementally (`on_chunk`, lines 129-134, committed every
`_OUTPUT_COMMIT_INTERVAL=20` chunks). Status is only ever set to `COMPLETED` when `result.succeeded` is
`True` from a real subprocess/API call (`adapters.py` — see C section). This part is real and verified by
reading the full code path, not merely declared.

### B5. Agent communication & collaboration
**Status: NOT IMPLEMENTED.**
No "shared workflow state" blob, no task-contract JSON Schema, and no inter-agent messaging exist anywhere
in `backend/app/models/` or `backend/app/services/`. `Workflow` (`backend/app/models/workflow.py`) is a flat
ordered list of `Task` rows run sequentially in one thread
(`workflow_execution.py:_run_workflow`, lines 29-82) — each step is executed independently via the same
`execute_task()` call used for a standalone task. There is no mechanism for step N's agent to read
step N-1's structured output as "shared state" beyond whatever plain text ended up in `task.output`/
`task.git_diff`, and no agent-to-agent or agent-to-supervisor message passing. The decision log's "Controlled
Agent Communication" subsystem (§461-503, §964) is entirely absent.

### B6. Lifecycle / monitoring
**Status: PARTIALLY IMPLEMENTED.**
`TaskStatus` = `NOT_STARTED / RUNNING / COMPLETED / FAILED` (`task.py:13-17`); `WorkflowStatus` is the same
4 states (`workflow.py:13-17`). `started_at`/`completed_at`/`cancel_requested` are real DB columns updated by
real code. There is no richer lifecycle (queued/retrying/escalated/paused), no agent-level health/uptime
dashboard beyond the per-connection `health_check()` probe described in C, and no execution-trace/telemetry
store (grepped the whole backend for `trace_id`, `execution_trace`, `tracing` — zero matches).

### B7. Failure handling
**Status: IMPLEMENTED AND VERIFIED (fail-honest, no retry/escalation).**
Every failure branch in `execute_task()` sets `task.status = TaskStatus.FAILED` with a real
`task.error_message` (no connection assigned → line 70-74; connection/adapter missing → 78-83; not
connected → 94-99; worktree failure → 120-125; adapter `succeeded=False` → 154-157; diff-collection or
push/PR failure is captured as an appended note without overturning the task's own success verdict,
156-168, 206-208). `workflow_execution.py:71-75` halts the whole workflow on the first failed step and marks
remaining steps as never started. This is honest failure propagation, but there is **no automatic retry, no
failure classification, and no escalation policy** — a failure is terminal, matching the project's
"never fabricate success" philosophy but falling well short of the decision log's richer failure-recovery
design (§50 "Agent failure recovery and provider handover").

### B8. Agent replacement / handoff
**Status: NOT IMPLEMENTED.**
Grep across `backend/app/**/*.py` for `handoff`, `hand-off`, `replace.*agent`, `agent.*replace`, `reassign`
returned **zero matches**. There is no code path, model field, or endpoint that lets a different connection/
adapter pick up an in-progress task. Checked specifically for the elements the task asked about:
- Original instruction: only `task.description`/`task.title` persist — a plain string, reusable by a new
  run, but nothing packages it as a "handover."
- Approved plan: no plan entity exists at all (no planning/approval model anywhere in `backend/app/models/`).
- Repo state / branch / changed files / git diff: these *do* persist on the `Task` row
  (`git_branch_name`, `git_base_branch`, `git_diff`, `git_changed_files` — `task.py:70-73`), and the
  worktree itself (`_worktree_root()/<task.id>`, `git_worktree.py:108`) is kept on disk per-task, so in
  principle a human (not any backend code) could point a different CLI at that same worktree path.
- Completed/remaining steps: workflow has `current_step_index` (`workflow.py:44`) so partial progress
  across *workflow steps* is tracked, but there is no sub-step/partial-task-progress model within a single
  task's own execution (a task is atomic: one prompt in, one result out).
- Execution logs / test results / review comments: execution output is just `task.output` (raw
  concatenated stdout/API text); there is no structured log model. Test results and review comments have
  **no backing model at all** — the frontend explicitly states this (see fragment doc, section D6).
- Resumability: nothing re-attaches to a previous session. `ClaudeCodeAdapter.capabilities()` lists
  `Capability("Resume session", CapabilityState.DECLARED)` (`adapters.py:533`) but `start_execution`/
  `start_execution_streaming` (`adapters.py:543-556`) never pass a session ID, and no session-ID field
  exists on `Task` or `CodingAgentConnection`. Every execution — whether it is the "first" run or a
  hypothetical "replacement" run — is `claude -p <prompt>`, i.e. **always a fresh, stateless CLI
  invocation**, never a resumed one.

**Conclusion for B8:** "Replacement" is not a real backend concept; there is no code that performs a
handoff. The only things that would survive a manual re-run of the same task (by a human re-triggering it)
are the git branch/diff/changed-files already committed to the worktree and DB row, plus the plain-text
task description. Approved plan, execution logs, test results, and review comments do not exist to hand
over because those entities themselves don't exist. This is a stateless "start over" model, not a
resumable handoff, and is **NOT IMPLEMENTED** against the decision log's "versioned handover packages"
requirement.

### B9. Session persistence
**Status: NOT IMPLEMENTED.** No `session_id`/thread-id persistence anywhere in `agent_runtime/` or on
`Task`/`CodingAgentConnection`. `backend/app/models/session.py` exists but (confirmed via `models/__init__.py`)
is the HTTP/user `Session` model, unrelated to agent conversation sessions.

---

## C. Provider Integrations

### C1. Common Agent Runtime Interface
**Status: IMPLEMENTED AND VERIFIED — but only one adapter family, not two.**
`backend/app/services/agent_runtime/base.py` defines a single abstract class,
`CodingAgentRuntimeAdapter(ABC)` (lines 52-113), with abstract `capabilities()`, `health_check()`,
`start_execution()`, and a default-implemented `start_execution_streaming()`. This is a genuine common
interface — every adapter implements it uniformly, and `registry.py` instantiates all six adapters behind
it (`_ADAPTERS` dict, lines 11-21). **However**, the decision log's Decision 1 (§1194-1227, PI-02 at §1312)
explicitly calls for "Separate LLM and coding-agent adapter families." This codebase has only the
coding-agent family; LLM providers (OpenAI, Gemini, DashScope/Qwen) are wedged into the same
`CodingAgentRuntimeAdapter` interface via their respective adapters' `health_check`/`start_execution`
methods calling plain chat-completion endpoints (e.g. `CodexAdapter.start_execution` →
`_run_openai_prompt`, `adapters.py:579-581`). There is no distinct `LLMRuntimeAdapter` base class anywhere
in the codebase (confirmed by reading the full file — only one ABC is declared). **PARTIALLY IMPLEMENTED**
against PI-02.

### C2. LLM adapters vs. coding-agent adapters
**Status: FRONTEND/NAMING ONLY — not actually separated in code.**
All six registered adapters (`ClaudeCodeAdapter`, `CodexAdapter`, `GeminiCliAdapter`, `QwenAdapter`,
`DockerSandboxAdapter`, `CustomAdapter`) share the identical class hierarchy and `slug`/`display_name`
pattern; "coding agent" vs. "LLM" is a documentation distinction, not a type distinction. See C1.

### C3. Which providers are genuinely connected/executable vs. just listed
Each adapter's real behavior, read directly from `adapters.py`:

| Adapter | No credential path | With credential path | Verified real? |
|---|---|---|---|
| `ClaudeCodeAdapter` | Shells out to local `claude -p <prompt> --permission-mode acceptEdits` via `shutil.which`/`subprocess.run` (lines 538-556) | Calls real Anthropic Messages API (`_run_anthropic_prompt`, hardcoded model `claude-3-5-haiku-20241022`, line 159) | YES — genuine CLI exec or genuine HTTPS call, not simulated |
| `CodexAdapter` | `codex exec <prompt>` via subprocess | Real OpenAI `chat/completions` call, model `gpt-4o-mini` hardcoded (line 236) | YES |
| `GeminiCliAdapter` | `gemini -p <prompt>` via subprocess | Real Gemini `generateContent` call, model `gemini-1.5-flash` hardcoded (line 308) | YES |
| `QwenAdapter` | `qwen -p <prompt>` via subprocess | Real DashScope `chat/completions` call, model `qwen-plus` hardcoded (line 405) | YES |
| `DockerSandboxAdapter` | Runs the task prompt as a shell command inside `docker run --rm --network none --memory 256m --cpus 0.5` (lines 688-699) — real isolation flags, not just documented | N/A (no credential) | YES, if Docker is actually installed/running (`_docker_daemon_status`, lines 663-685, does a real `docker version` call) |
| `CustomAdapter` | N/A | Real HTTP GET/POST to a user-configured endpoint URL used *as* the credential value (lines 813-838) | YES, generic passthrough |

All adapters are genuinely executable *if* their underlying CLI/API/daemon is actually present/reachable on
the host — none fabricate success. This matches the module's own stated design intent (docstring,
`adapters.py:1-8`): "CLI detection shells out to the real binary on PATH; nothing is faked." **IMPLEMENTED
AND VERIFIED** for all six, conditioned on the environment actually having the binary/daemon/credential —
this audit did not independently confirm any of `claude`/`codex`/`gemini`/`qwen`/`docker` binaries are
installed on this machine, so "connected" status for any specific adapter today is UNKNOWN/environment-
dependent, not confirmed true at audit time.

### C4. Model configuration
**Status: MOCKED-HARDCODED.** Every model name is a Python literal inside the adapter function
(`claude-3-5-haiku-20241022`, `gpt-4o-mini`, `gemini-1.5-flash`, `qwen-plus` — see table above). There is no
per-connection or per-task model selection field on `CodingAgentConnection` or `Task`, and no admin UI/DB
column to change the model without editing source. "Model version pinning" exists only in the trivial sense
that the hardcoded string is a pinned version — there is no versioning *policy* or override mechanism as the
decision log implies (§1227-1240 discusses pinning as a deliberate operational control, not an accidental
hardcode).

### C5. Credential management
**Status: IMPLEMENTED AND VERIFIED.** `Credential` model (`agent_runtime.py:26-41`) stores
`encrypted_value` (via `app.core.crypto.decrypt_value`, used in `task_execution.py:89`), is org-scoped, and
is never returned by the API per its own docstring. `backend/app/api/routes/agent_runtimes.py` exposes
create/list/delete/recheck endpoints (`create_connection`, `list_connections`, `delete_connection`,
`recheck_connection` — lines 121-223). This part is real.

### C6. Provider routing / fallback policy
**Status: NOT IMPLEMENTED.** There is exactly one `CodingAgentConnection` per `(organization_id,
runtime_slug)` (unique constraint, `agent_runtime.py:48-50`), and a `Task` points at exactly one connection
via a single FK. No code selects among multiple candidate providers, no fallback-on-failure logic exists
(a failed adapter call simply fails the task — `task_execution.py:154-157`), and no "policy" table/config
governs routing. The decision log's "policy-controlled provider routing" and "provider comparisons
segmented by agent role" (§886-944, §1365-1389) are entirely absent from the code.

### C7. Provider health monitoring
**Status: IMPLEMENTED AND VERIFIED (on-demand, not continuous).** `health_check()` on every adapter performs
a real probe (CLI `--version` detection via `_detect_cli_version`, or a real API call like
`_probe_anthropic_api`/`_probe_openai_api`/`_probe_gemini_api`/`_probe_qwen_api`, or `_docker_daemon_status`
for Docker). It is invoked both from the `recheck_connection` route and defensively again right before every
task execution (`task_execution.py:93`, explicitly to avoid trusting a stale cached value). There is no
background/scheduled health-monitoring loop — it is purely synchronous, request-triggered.

### C8. Cost tracking
**Status: NOT IMPLEMENTED.** Grepped the entire backend for `cost_tracking`, `token_usage`, `cost_usd`,
`usage_cost` — zero matches. No token/cost accounting exists anywhere; API responses from providers are not
even parsed for usage fields (e.g. `_run_openai_prompt` discards everything except `choices[0].message.content`,
`adapters.py:245-249`).

### C9. Execution tracing
**Status: NOT IMPLEMENTED.** Grepped for `trace_id`, `execution_trace`, `tracing` — zero matches anywhere
in `backend/app`. The only execution record is the flat `task.output` text blob plus start/complete
timestamps; there is no structured span/trace of sub-steps, tool calls, or provider round-trips.

---

## Summary table

| Feature | Status |
|---|---|
| Agent registration | PARTIALLY IMPLEMENTED (connection, not agent, model) |
| Agent roles / capability schema | MOCKED-HARDCODED (flat list, no hierarchy/role taxonomy) |
| Agent assignment | IMPLEMENTED BUT NOT VERIFIED (trivial FK, no registry/ranking/escalation) |
| Agent execution | IMPLEMENTED AND VERIFIED |
| Agent communication / shared state | NOT IMPLEMENTED |
| Agent lifecycle / monitoring | PARTIALLY IMPLEMENTED |
| Failure handling | IMPLEMENTED AND VERIFIED (fail-honest; no retry/escalation policy) |
| Agent replacement / handoff | NOT IMPLEMENTED |
| Session persistence / native resume | NOT IMPLEMENTED |
| Common Agent Runtime Interface | IMPLEMENTED AND VERIFIED (single family, not two) |
| Separate LLM vs. coding-agent adapter families | PARTIALLY IMPLEMENTED (naming only) |
| Provider executability (6 adapters) | IMPLEMENTED AND VERIFIED (environment-dependent at runtime; not independently confirmed on this host) |
| Model configuration / version pinning policy | MOCKED-HARDCODED |
| Credential management | IMPLEMENTED AND VERIFIED |
| Provider routing / fallback | NOT IMPLEMENTED |
| Provider health monitoring | IMPLEMENTED AND VERIFIED (synchronous, not continuous) |
| Cost tracking | NOT IMPLEMENTED |
| Execution tracing | NOT IMPLEMENTED |
| Docker isolation (sandbox adapter only) | IMPLEMENTED AND VERIFIED |
| Git worktree isolation per task | IMPLEMENTED AND VERIFIED |
