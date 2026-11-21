# 06 — Security, Governance and Guardrails Audit

Scope: `backend/app/core/`, `backend/app/api/deps.py`, `backend/app/services/access.py`, `backend/app/services/agent_runtime/adapters.py`, `backend/app/services/git_worktree.py`, `backend/app/core/crypto.py`, `backend/.env`, `backend/app/main.py`. Read-only audit; no application files modified.

Status legend: IMPLEMENTED AND VERIFIED / IMPLEMENTED BUT NOT VERIFIED / PARTIALLY IMPLEMENTED / FRONTEND ONLY / BACKEND ONLY / MOCKED-HARDCODED / NOT IMPLEMENTED / BLOCKED.

---

## 1. Authentication

**Status: IMPLEMENTED AND VERIFIED**

- `backend/app/core/security.py`: real bcrypt password hashing (`bcrypt.hashpw`/`checkpw`), JWT access tokens signed HS256 (`create_access_token`, `decode_token`), opaque refresh tokens (`secrets.token_urlsafe(48)`) stored only as SHA-256 hashes (`hash_refresh_token`) in `SessionModel` (`backend/app/models/session.py`) — the raw refresh token is never persisted.
- `backend/app/api/routes/auth.py`: `/auth/register`, `/auth/login`, `/auth/refresh` (rotates: revokes old session, issues new pair), `/auth/logout` (revokes), `/auth/me`. Inactive users (`user.is_active`) are rejected at login and token resolution.
- `backend/app/api/deps.py::get_current_user` validates bearer JWT, checks `type == "access"` (so a refresh token can't be replayed as an access token), re-loads the user from DB (so a deactivated user's tokens stop working mid-lifetime, not just at next login).
- VERIFIED THIS AUDIT: `backend/tests/test_auth.py` and the auth-dependent fixtures in `test_organizations_and_projects.py`, `test_tasks.py`, `test_presence.py`, etc. pass (see report 07).

**Dev-only backdoor (by design, but flagged):** `/auth/dev-login` (`auth.py:102-129`) issues real tokens with no password check. It 404s unless both `SF_DEV_QUICK_LOGIN_ENABLED=true` and `SF_DEV_QUICK_LOGIN_EMAIL` are set. **Finding:** in the actual checked-in `backend/.env` on this machine, `SF_DEV_QUICK_LOGIN_ENABLED=true` and `SF_DEV_QUICK_LOGIN_EMAIL=adiraj2503@gmail.com` are set — i.e. on this deployment the passwordless login endpoint is live right now, not merely available-but-off. This is explicitly documented in code comments as a local-dev convenience, but it is a real authentication bypass that must never ship enabled to a shared or production environment; there is no separate build-time guard beyond this one runtime flag.

**Missing controls:**
- ~~No rate limiting or lockout on `/auth/login` or `/auth/register`~~ **RESOLVED 2026-11-21 (P0-3):** `backend/app/core/rate_limit.py` adds an in-memory sliding-window limiter (single-process scope, noted in its own docstring as needing a shared store such as Redis for a multi-worker/multi-instance deployment); applied to `/auth/register` (8/min/IP), `/auth/login` (15/min/IP), `/auth/dev-login` (shares the login limit). Verified by `tests/test_auth.py::test_login_rate_limited_after_repeated_attempts` and `::test_register_rate_limited_after_repeated_attempts` (both assert a real 429 after the threshold).
- No password complexity/breach checks, no MFA, no account lockout after failed attempts. **NOT IMPLEMENTED.**
- No email verification. **NOT IMPLEMENTED.**

**Phase 0 remediation (2026-11-21):** the dev-login bypass and placeholder-secret findings above are now structurally guarded, not just documented:
- `SF_ENVIRONMENT` (new setting, `backend/app/core/config.py`, default `"development"`) gates both. `get_settings()` now calls `_validate_non_local_settings`, which raises `RuntimeError` at startup if `SF_ENVIRONMENT` is anything other than development/local/dev **and** `SF_JWT_SECRET`/`SF_CREDENTIAL_ENCRYPTION_KEY` are still their placeholder defaults, or `SF_DEV_QUICK_LOGIN_ENABLED` is true — a shared/production deployment can no longer silently boot with any of these. Verified by `tests/test_config_security.py` (5 cases: local-dev tolerates placeholders, non-local rejects each of the three conditions individually, non-local with real secrets is fine).
- `backend/app/api/routes/auth.py::_dev_login_permitted` adds a second, independent guard on both `/auth/dev-login` routes: the bypass now requires `settings.is_local_dev` in addition to the existing `dev_quick_login_enabled` flag, so a non-local `.env` that mistakenly sets the flag still 404s. Verified by `tests/test_auth.py::test_dev_login_404_when_disabled`.
- This machine's own `.env` is unchanged (still local dev, by design) — the fix is the structural guard for any *other* deployment, not a rotation of this developer's own working secrets. Rotating this machine's own `SF_JWT_SECRET`/`SF_CREDENTIAL_ENCRYPTION_KEY` was intentionally not done as part of this pass since it would invalidate every live session/credential on the one environment actually in use, for no security benefit (this `.env` is gitignored and never leaves local dev).

## 2. Authorization / RBAC

**Status: IMPLEMENTED AND VERIFIED**

- `backend/app/api/deps.py`: `require_org_member`, `require_org_admin`, `require_project_access`, `effective_project_role`. Org-admin falls back to implicit `PROJECT_ADMIN` on any project in that org (`effective_project_role`, lines 92-100); explicit project membership otherwise governs.
- `backend/app/services/access.py::visible_project_ids` computes the same rule in bulk for list/dashboard endpoints — same semantics as the per-request dependency, read end-to-end.
- `ProjectContext.require_role(allowed: set[ProjectRole])` is the route-level enforcement point used across `tasks.py`, `workflows.py`, `projects.py`, `git_integration.py`, `knowledge.py`.
- VERIFIED THIS AUDIT by running the suite: `test_organizations_and_projects.py::test_non_member_cannot_access_organization`, `test_non_admin_cannot_invite_members`, `test_last_admin_cannot_be_demoted`, `test_developer_cannot_update_project`, `test_cross_organization_isolation`, `test_project_create_and_isolated_visibility` — all passed (route → `deps.py` → DB membership tables, traced and exercised).
- `test_tasks.py::test_viewer_cannot_create_task`, `test_connection_from_another_org_is_rejected`; `test_workflows.py::test_viewer_cannot_create_workflow`; `test_knowledge.py::test_viewer_without_project_access_cannot_sync` / `test_graph_endpoint_requires_project_access` — all passed, confirming 403s are real, not just documented.

**Gap:** Roles are coarse (`OrgRole.ORG_ADMIN`/member; `ProjectRole` viewer/developer/admin per grep of tests). No fine-grained per-resource ACLs beyond project/org membership; no row-level policy engine. This matches a small-team product's needs but is a genuine limitation for larger governance requirements. PARTIALLY IMPLEMENTED relative to a full RBAC matrix (resource-level permissions, custom roles) — simple, hard-coded 2-3 tier role model instead.

## 3. Secrets management / credential isolation

**Status: PARTIALLY IMPLEMENTED**

- `backend/app/core/crypto.py`: user-supplied provider credentials (Anthropic/OpenAI/Gemini/Qwen/custom-adapter API keys, stored via `Credential` model, `backend/app/models/agent_runtime.py`) are encrypted at rest with Fernet, keyed by SHA-256 of `SF_CREDENTIAL_ENCRYPTION_KEY` (`core/crypto.py:9-12`). `decrypt_value` is only called at point of use in `task_execution.py:89` and workflow execution equivalent. **IMPLEMENTED AND VERIFIED** (code path read end-to-end: route → `Credential.encrypted_value` → `decrypt_value` → adapter call).
- **Finding — plaintext secrets at rest in the repo's `.env`:** `backend/.env` (read during this audit) contains, in plaintext: `SF_JWT_SECRET=dev-secret-change-me`, `SF_CREDENTIAL_ENCRYPTION_KEY=dev-credential-key-change-me` (both literally the insecure placeholder default from `config.py`, not rotated), and a full PEM-encoded GitHub App RSA private key (`SF_GITHUB_APP_PRIVATE_KEY`) plus `SF_GITHUB_APP_ID`. The JWT secret and credential-encryption key being left at their documented placeholder default means: (a) any attacker who can forge or guess this static secret can mint valid access tokens for any user id without ever authenticating, and (b) all "encrypted" provider API keys in the DB are only as strong as a widely-known-to-be-insecure default key. This is a dev-environment misconfiguration, not a code defect, but it is the literal state of the one environment available to audit, so it is reported as a concrete, exploitable finding rather than a theoretical one.
- No secrets manager / KMS integration (Vault, AWS Secrets Manager, etc.) — everything is `.env` + `pydantic_settings`. **NOT IMPLEMENTED** for anything beyond file-based config, which is reasonable for a self-hosted dev tool but should be flagged before production use.
- The GitHub App private key is read directly from settings and used by `backend/app/services/git_provider/github_app.py` (not separately re-encrypted at rest beyond whatever the `.env` file's OS permissions provide).

## 4. Prompt injection protection

**Status: NOT IMPLEMENTED**

- `task_execution.py:142-148`: the task's own `description or title` (fully user-controlled, no sanitization, no system/user role separation beyond what each CLI/API itself imposes) is passed directly as the prompt to whichever adapter is configured (`adapter.start_execution_streaming(task.description or task.title, ...)`). There is no injection-detection, no prompt firewall, no output scanning for exfiltration patterns anywhere in `backend/app/services/agent_runtime/` or `task_execution.py`/`workflow_execution.py`.
- This is consistent with the project's stated design ("never a fabricated success," per the adapters' docstrings) — it is an *honesty* layer, not a *safety* layer. A malicious or compromised task description could direct a locally-installed coding-agent CLI (Claude Code, Codex, Gemini, Qwen) to do anything that CLI's own tool-permission model allows inside the worktree. The only mitigation present is `ClaudeCodeAdapter`'s `--permission-mode acceptEdits` (adapters.py:511-519), which auto-approves file edits but still gates Bash through Claude Code's own CLI — this is the *CLI's* guardrail, not one enforced by Software Factory itself.
- **Conclusion:** no prompt-injection-specific control exists in this codebase. This should be treated as a known gap, not a partial implementation, since nothing was found to grade as "partial."

## 5. Tool permission enforcement / sandbox isolation / command execution policy

**Status: PARTIALLY IMPLEMENTED (adapter-dependent — real for one adapter, absent for the rest)**

- `backend/app/services/agent_runtime/adapters.py::DockerSandboxAdapter` (`_sandbox_command`, lines 688-699) is a genuine sandbox: `docker run --rm --network none --memory 256m --cpus 0.5`, bind-mounting the task's worktree read/write at `/workspace`. **VERIFIED THIS AUDIT**: ran `backend/tests/test_docker_sandbox.py` directly against the real local Docker daemon (confirmed reachable via `docker ps`) — all 6 tests passed, including `test_sandbox_has_no_network_access` (a DNS lookup from inside the container genuinely fails) and `test_cancelling_a_real_sandboxed_task_actually_stops_the_container` (process is actually terminated, not merely marked cancelled). This is real, enforced isolation, not a label.
- Every other coding-agent adapter (`ClaudeCodeAdapter`, `CodexAdapter`, `GeminiCliAdapter`, `QwenAdapter`) in `local_runtime` mode shells out directly to the CLI binary on the **backend host's own PATH** via `subprocess.run`/`Popen` (`_run_cli_prompt`, `_run_cli_prompt_streaming`, adapters.py:54-146) with **no sandboxing, no network restriction, no resource limit, no filesystem jail** beyond the `cwd` worktree the CLI is launched *in* (which does not stop the CLI from reading/writing/exec'ing anything else the backend process's OS user can reach). This is confirmed by reading `start_execution`/`start_execution_streaming` for each of those four adapters end-to-end — none of them routes through Docker or any other isolation primitive.
- **Finding:** "sandbox isolation" and "command execution policy" are genuinely enforced only for the `docker_sandbox` runtime. For the four LLM-CLI runtimes, the isolation story is "whatever the underlying CLI's own permission flags do" (verified for Claude Code only, by inspection — `--permission-mode acceptEdits` gates file edits but not Bash), which is not something Software Factory itself enforces or audits. This is a material production-readiness gap if any of those runtimes are used with untrusted task input.
- `git_worktree.py` (not fully read in this pass, but referenced via `task_execution.py`) bounds filesystem edits a task *reports* to a dedicated branch/worktree per task — this is real isolation of *what the diff/PR captures*, not of what the process underneath was allowed to touch.

## 6. Repository access restrictions

**Status: IMPLEMENTED BUT NOT VERIFIED (code read, not exercised against a real GitHub App install in this audit)**

- `backend/app/services/git_provider/github_app.py` + `backend/app/models/git_integration.py` model a GitHub App installation scoped per organization/connection; `RepositoryConnection` ties one project to one repo via that installation. Access to trigger pushes/PRs flows through `require_project_access`/role checks before `git_worktree`/`git_provider` code runs (confirmed by reading `tasks.py` route wiring and `task_execution.py`'s call sequence). `backend/tests/test_git_integration.py` exercises this with a mocked GitHub API (not live) — passed (112/116 suite, see report 07), but that is confirmation of the app's own logic, not of GitHub App token scoping in production.
- Branch protection is only ever *read and displayed*, never enforced by this backend (`task_execution.py:190-205`, and explicitly stated in that file's module docstring: "This backend never enforces or bypasses them; GitHub's own merge button is what actually requires them."). This is an accurate, honest design choice, not a gap, but worth stating plainly: Software Factory provides no governance gate of its own on top of GitHub's.

## 7. Data isolation (multi-tenant)

**Status: IMPLEMENTED AND VERIFIED**

- Verified via the same `require_project_access`/`require_org_member` chain and `backend/tests/test_organizations_and_projects.py::test_cross_organization_isolation`, `test_project_create_and_isolated_visibility` — both pass. These tests create two orgs/projects under different owning users and assert that neither users' data nor project visibility leaks across the boundary; ran this audit, both green.
- No row-level security at the Postgres level (plain SQLAlchemy `filter_by` scoping) — isolation is entirely application-enforced. A bug in any one route's query could in principle leak cross-tenant data; there's no defense-in-depth DB-level backstop. Flagged as a design limitation, not a demonstrated breach.

## 8. Audit logging

**Status: PARTIALLY IMPLEMENTED**

- `backend/app/services/audit.py::record()` is a thin, real DB-writing helper (`AuditLog` model, `backend/app/models/audit.py`) called from 7 route modules (`auth.py`, `tasks.py`, `git_integration.py`, `workflows.py`, `agent_runtimes.py`, `projects.py`, `organizations.py` — confirmed by grep). Login/register/dev-login, and presumably task/workflow/connection lifecycle events, are recorded with `actor_user_id`, `organization_id`, `target_type/id`, free-form `extra` JSON.
- **Not verified in this pass:** whether *every* sensitive mutation (e.g. role changes, credential creation/rotation, project deletion) actually calls `audit.record` was not individually traced for all ~7 files; this would need a route-by-route pass to state as VERIFIED. Treat the coverage claim as IMPLEMENTED BUT NOT FULLY VERIFIED.
- No tamper-evidence (no hash chaining, no write-once storage) and no retention/export tooling found. There is no UI surfaced for audit log review in `frontend/src/app/features/` under an obvious name — a targeted search found no audit-log feature folder, so the audit trail is backend-only with no frontend consumer. **BACKEND ONLY.**

## 9. Human approval gates

**Status: NOT IMPLEMENTED (backend) / MOCKED-HARDCODED (frontend)**

- Backend: no model, table, or route for "approval" exists anywhere in `backend/app` (confirmed — a case-insensitive grep for "approval" across `backend/app` returned zero matches). Starting a task (`POST /tasks/{id}/start`) executes immediately once a user with sufficient role calls it; opening a PR likewise happens automatically inside `execute_task` with no separate approve-before-push/approve-before-PR step. The only "gate" is GitHub's own branch protection (read-only, not enforced by this app — see §6).
- Frontend: `frontend/src/app/features/approvals/approvals.component.ts` exists and renders a full approvals UI, but it is built entirely on `MockDataService` (`this.data = inject(MockDataService); this.approvals = this.data.approvals;`) and a hardcoded `recentDecisions` array of fake timestamped entries (lines 22-27 of that file). There is no backend endpoint it calls. **MOCKED-HARDCODED.**

## 10. Sensitive data protection / output validation

**Status: PARTIALLY IMPLEMENTED**

- Credentials are encrypted at rest (§3). Task output/diffs are stored in plaintext in Postgres with no PII/secret scrubbing before display or before being embedded into the knowledge graph (`knowledge_graph.py` sync, see report 04/05 if covering that service) — not verified as a scrubbing gap specifically, but no redaction logic was found in `task_execution.py` or `knowledge_graph.py` during this pass.
- No agent-output validation layer (e.g. schema-checking or safety-checking what a coding agent CLI actually produced before it's trusted) beyond the honesty invariant described in `task_execution.py`'s docstring ("only ever marked completed when the adapter actually returned succeeded=True"). That invariant protects against *false success reporting*, not against *unsafe but "successful"* output.

## 11. CORS / transport

**Status: IMPLEMENTED BUT NOT VERIFIED**

- `backend/app/main.py` wires `CORSMiddleware` with origins from `SF_CORS_ORIGINS` (default `["http://localhost:4200"]`), confirmed in `config.py`. Not verified whether `allow_credentials`/`allow_methods` are set permissively — would need a direct read of the middleware call args in `main.py` beyond the import line found here.

---

## Summary table

| Control | Status |
|---|---|
| Authentication (password + JWT + refresh rotation) | IMPLEMENTED AND VERIFIED |
| Dev-login bypass disabled-by-default design | IMPLEMENTED AND VERIFIED (code); **currently enabled** in this deployment's `.env` — operational risk |
| Login rate limiting / brute-force protection | NOT IMPLEMENTED |
| RBAC (org/project roles) | IMPLEMENTED AND VERIFIED |
| Fine-grained/custom permissions | NOT IMPLEMENTED (coarse roles only) |
| Credential encryption at rest | IMPLEMENTED AND VERIFIED |
| Secrets management (KMS/Vault) | NOT IMPLEMENTED (.env only; placeholder keys found live) |
| Prompt injection protection | NOT IMPLEMENTED |
| Sandbox isolation — Docker Sandbox runtime | IMPLEMENTED AND VERIFIED |
| Sandbox isolation — Claude Code/Codex/Gemini/Qwen local runtimes | NOT IMPLEMENTED (direct host exec) |
| Repository access scoping (GitHub App) | IMPLEMENTED BUT NOT VERIFIED (live) |
| Branch protection enforcement | NOT IMPLEMENTED (by design — read-only display) |
| Multi-tenant data isolation | IMPLEMENTED AND VERIFIED |
| Audit logging | PARTIALLY IMPLEMENTED (backend only, coverage not fully traced) |
| Human approval gates | NOT IMPLEMENTED (backend); MOCKED-HARDCODED (frontend UI) |
| Agent output validation/safety scanning | NOT IMPLEMENTED |

**Bottom line for production use:** the core auth/RBAC/tenant-isolation skeleton is real and test-verified. The blocking gaps for production are: (1) the dev-login bypass and placeholder JWT/encryption secrets currently live in this environment's `.env`, (2) no rate limiting anywhere, (3) no sandboxing for any coding-agent runtime except Docker Sandbox, (4) no prompt-injection or agent-output-safety layer, and (5) no real human-approval gate before a task runs or a PR is opened — only a mocked frontend screen exists for that concept.
