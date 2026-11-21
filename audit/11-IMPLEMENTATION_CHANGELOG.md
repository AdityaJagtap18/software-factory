# 11 — Implementation Changelog

Running record of implementation work done against `09-SOFTWARE_FACTORY_REMAINING_ROADMAP.md`, in the order
it happened. Each entry: what changed, why, how it was verified. Newest first.

---

## 2026-11-21 — Phase 2: Foundational Gaps (P2-1 Graph Access Service, P2-2 schema, P2-3 CLI sandboxing plumbing, P2-4 Agent Registry)

**Why:** The roadmap's own sequencing put this immediately after Phase 0, and flagged it as blocking later
work (Repository KG↔Git wiring, multi-agent orchestration) from widening an already-ungated graph-access
surface. The urgency was concrete, not theoretical: this session's own earlier, already-uncommitted
`knowledge_context.py` work had added a *second* caller doing raw Cypher straight against the driver,
exactly the risk `04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` S3.5 warned about.

**P2-1 — Graph Access Service:**
- New `backend/app/services/graph_access.py`: `GraphAccessService`, constructed only via
  `from_project_context(ctx)` (HTTP routes, scope from the already-authorized `ProjectContext`) or
  `from_project(project)` (trusted server-internal callers, e.g. background task execution, which have
  already loaded `project` through their own authorization path). No method on the class accepts a
  caller-supplied project id — this is a structural guarantee, not a convention, and is directly tested.
- `backend/app/api/routes/knowledge.py`: all four routes now go through the service instead of calling
  `knowledge_graph` directly.
- `backend/app/services/knowledge_context.py`: its ad hoc relevance-query Cypher now runs through
  `GraphAccessService.from_project(project).session()` instead of `knowledge_graph._driver().session()`
  directly — closing the exact gap described above.
- Tests: `backend/tests/test_graph_access.py` — a real two-tenant test proving data-level isolation (not
  just an HTTP 403, which `test_knowledge.py` already covered), plus a structural test asserting no method
  on `GraphAccessService` has a `project_id` parameter.

**P2-2 — Knowledge graph schema:**
- `knowledge_graph.ensure_schema()` extended: it already created constraints for the six platform-entity
  labels (Project/Repository/User/Task/Workflow/Connection) from earlier, uncommitted work — this change
  adds composite-key constraints for File/Directory/Module/Class/Function (previously **none**, despite
  being the highest-cardinality, most heavily MERGE'd labels) plus `project_id` range indexes on
  File/Class/Function.
- `backend/app/main.py`: `ensure_schema()` now runs at app startup via a FastAPI lifespan context manager
  (replacing a deprecated `@app.on_event("startup")` pattern introduced in the same edit, fixing a
  deprecation warning rather than leaving it), not only lazily on first sync/ingest call. Best-effort: if
  Neo4j isn't reachable at startup, it no-ops honestly rather than blocking API startup.

**P2-3 — Sandbox local-CLI adapters (plumbing only — see honest caveat below):**
- New `_sandboxed_cli_command`/`_run_cli_prompt_sandboxed`/`_run_cli_prompt_streaming_sandboxed` in
  `adapters.py`, mirroring the existing `DockerSandboxAdapter` primitives but **with network left enabled**
  (these CLIs must reach their own provider API — unlike `docker_sandbox`'s fully offline mode), still
  memory/CPU-limited and filesystem-jailed to the task worktree.
- Four new `Settings` fields (`claude_code_sandbox_image`, `codex_sandbox_image`, `gemini_cli_sandbox_image`,
  `qwen_sandbox_image`), all defaulting to `""`. `ClaudeCodeAdapter`, `CodexAdapter`, `GeminiCliAdapter`, and
  `QwenAdapter`'s `start_execution`/`start_execution_streaming` now check the relevant setting and route
  through the sandboxed path when it's set, falling back to today's direct-host execution when it's empty.
- **Honest caveat, stated plainly:** no real Docker image with Claude Code/Codex/Gemini CLI/Qwen actually
  installed exists in this repository or environment. All four settings are empty by default, so **this
  change has zero effect on behavior in any environment today** — every adapter still runs directly on the
  backend host, exactly as `06-SECURITY_AND_GOVERNANCE_AUDIT.md` §5 described. What's real: the mechanism
  itself is verified against the live Docker daemon (worktree bind-mount, resource limits, real network
  reachability via a live DNS lookup, real mid-stream cancellation) using the `python:3.11-slim` image
  already used by `DockerSandboxAdapter` as a stand-in for "an image with the CLI installed." Building and
  verifying four real per-CLI images is a separate, concrete follow-up task, not attempted here — doing so
  without actually building and testing each image would have meant claiming sandboxing that doesn't exist,
  which this project's own stated principle ("never a fabricated success") rules out.
- Tests: `backend/tests/test_cli_sandboxing.py` — pure command-construction tests (no Docker needed); two
  `requires_docker` tests proving the real mechanism (network reachability, cancellation); one wiring test
  (via `monkeypatch`) proving `ClaudeCodeAdapter` only takes the sandboxed path when a sandbox image is
  configured, and takes the original path otherwise.

**P2-4 — Agent Registry foundation:**
- New `backend/app/models/agent.py` (`Agent`, `AgentStatus`), migration `3c99bb5de7e0_add_agent_registry`
  (additive — does not touch `coding_agent_connections`).
- New `backend/app/services/agent_registry.py::sync_agent_registry` — idempotent upsert from
  `all_adapters()`; an adapter that disappears from the registry is marked `deprecated`, never deleted (no
  loss of historical reference once something points at an `Agent` row).
- New `GET /agents` route (any authenticated user — same trust level as the existing, equally
  non-sensitive `GET /coding-agent-runtimes`), syncing the registry on each call.
- Deliberately deferred, per the roadmap's own "minimal" framing: no separate `AgentVersion` table (`version`
  is one free-form field on `Agent` itself) — real per-version history is Phase 5 territory, not built
  ahead of need.
- Tests: `backend/tests/test_agent_registry.py` — sync creates one row per real adapter, sync is idempotent,
  a removed adapter is deprecated not deleted, the endpoint requires auth and returns the real catalog.

**Verification:**
- Targeted runs (`test_graph_access.py`, `test_cli_sandboxing.py`, `test_agent_registry.py`,
  `test_knowledge.py`, `test_docker_sandbox.py`, `test_agent_runtimes.py`, `test_auth.py`,
  `test_config_security.py`) against the real, running Postgres + Neo4j + Docker: all pass except the same
  3 pre-existing, unrelated failures already present before this change
  (`test_runtime_catalog_lists_known_adapters`, `test_connections_default_to_not_configured`,
  `test_gemini_cli_health_check_verifies_cli_and_api_key` — all stem from the registry now including
  `ollama` and Gemini CLI's credential-less-connected behavior, both from already-uncommitted work that
  predates this session's Phase 2 changes, confirmed via `git diff --stat` showing this change never
  touched those adapters' registry entry or that specific health-check branch).
- Full-suite re-run after this change: **152 passed, 14 failed, 204.62s** — the exact same 14 pre-existing
  failures as the Phase 0 baseline (140 passed, 14 failed), confirming zero regressions; the 12 additional
  passing tests are exactly the new tests this change added (2 + 5 + 5).

**Roadmap status:** Phase 2 is **DONE**, with P2-3 explicitly partial (plumbing only, inert by default).
Recommended next: Phase 3 (test execution, Repository KG↔Git wiring, KG extraction breadth, multi-turn
conversation — though multi-turn follow-ups already exist per this session's own direct code reading, so
the roadmap's P3-4 status needs re-checking before scheduling it fresh — review comments, approvals gate).

---

## 2026-11-21 — Phase 0: Security & Configuration Hygiene (P0-1, P0-2, P0-3)

**Why:** Both the pre-existing audit (`06-SECURITY_AND_GOVERNANCE_AUDIT.md` §1/§3) and the roadmap agreed
this was the first, lowest-risk, fully-scoped item: the dev-login bypass and placeholder JWT/credential
secrets were live risks for any non-local deployment, and `/auth/login`/`/auth/register` had no throttling.

**What changed:**

- `backend/app/core/config.py`: added `environment: str = "development"` (`SF_ENVIRONMENT`) and
  `Settings.is_local_dev`. `get_settings()` now calls `_validate_non_local_settings`, which raises
  `RuntimeError` at startup if the environment is non-local **and** either secret is still its placeholder
  default, or `SF_DEV_QUICK_LOGIN_ENABLED` is true.
- `backend/app/api/routes/auth.py`: added `_dev_login_permitted()`, requiring `settings.is_local_dev` in
  addition to the existing `dev_quick_login_enabled` flag, on both `/auth/dev-login` routes. Added
  `_register_rate_limit`/`_login_rate_limit` dependencies to `/auth/register`, `/auth/login`,
  `/auth/dev-login`.
- `backend/app/core/rate_limit.py` (new): in-memory sliding-window limiter, single-process scope (noted in
  its own docstring — a multi-worker/multi-instance deployment needs a shared store such as Redis instead;
  not built since this backend runs single-process today). 8 requests/min/IP for register, 15/min/IP for
  login and dev-login.
- `backend/.env.example`: documented `SF_ENVIRONMENT`.
- Tests added: `backend/tests/test_config_security.py` (5 cases covering the fail-fast validator);
  `backend/tests/test_auth.py` (`test_dev_login_404_when_disabled`,
  `test_login_rate_limited_after_repeated_attempts`, `test_register_rate_limited_after_repeated_attempts`).
- `backend/tests/conftest.py`: `_clean_tables` now also resets the rate limiter between tests so the
  in-memory hit-counter doesn't leak across the suite.

**Explicitly not done:** this developer's own local `.env` was left unchanged — its placeholder secrets and
`SF_DEV_QUICK_LOGIN_ENABLED=true` are intentional local-dev convenience, now backed by a structural guard
rather than discipline alone. Rotating them here would only invalidate live local sessions for no security
benefit, since this `.env` is gitignored and never leaves the one machine.

**Verification:**
- `pytest backend/tests/test_auth.py backend/tests/test_config_security.py` — 14 passed, 1 pre-existing
  failure on the first run only (`test_register_and_login`, due to a stale test-database row left over from
  an earlier interrupted run against this same database, not from this change); after dropping and
  recreating `software_factory_test`, all 15 pass clean, including the 3 new tests this change added
  (`test_dev_login_404_when_disabled`, `test_login_rate_limited_after_repeated_attempts`,
  `test_register_rate_limited_after_repeated_attempts`) and the 5 in `test_config_security.py`.
- Full suite re-run (`pytest backend/tests/`), with the project's own Postgres and Neo4j containers started
  (both had to be brought up first — Docker Desktop itself was not running at the start of this session):
  **140 passed, 14 failed, 204.64s**. All 14 failures are **pre-existing and unrelated to this change** —
  every one is `TypeError: fake_streaming() got an unexpected keyword argument 'model'` in
  `test_agent_runtimes.py`/`test_tasks.py`/`test_workflows.py`'s mock adapters, coming from an
  already-uncommitted, in-progress change to `task_execution.py`/the adapter interface (adding per-task
  model selection) that landed in the working tree before this session started and whose test fixtures were
  only partially updated to match (confirmed via `git diff --stat`: this change touched only
  `config.py`/`auth.py`/`rate_limit.py`/`conftest.py`/`test_auth.py`/`test_config_security.py`/
  `.env.example`/the two audit docs — nothing in `task_execution.py`, `adapters.py`, `test_tasks.py`'s
  fixtures, or `test_workflows.py`'s fixtures). Flagging this as a known, separate pre-existing gap rather
  than silently leaving it unmentioned; not fixed as part of this Phase 0 pass since it's unrelated to
  security hygiene and belongs to whatever uncommitted model-selection work introduced it.
- Manually confirmed the backend still starts normally against this machine's own (local-dev) `.env`.

**Roadmap status:** Phase 0 is now **DONE**. Recommended next: Phase 2 (Graph Access Service + Neo4j
schema + sandbox-everywhere + Agent Registry foundation), per `09-SOFTWARE_FACTORY_REMAINING_ROADMAP.md`.
