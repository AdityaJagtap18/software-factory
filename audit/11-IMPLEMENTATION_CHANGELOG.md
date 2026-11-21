# 11 — Implementation Changelog

Running record of implementation work done against `09-SOFTWARE_FACTORY_REMAINING_ROADMAP.md`, in the order
it happened. Each entry: what changed, why, how it was verified. Newest first.

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
