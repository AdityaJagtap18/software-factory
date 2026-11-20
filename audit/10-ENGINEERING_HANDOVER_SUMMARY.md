# 10 — Engineering Handover Summary

This is the one document a time-pressed reviewer should read first. It is a synthesis of six independent,
evidence-based audits (`02`–`07`) plus the full current-state (`01`), gap analysis (`08`), and roadmap
(`09`) documents in this folder. Every claim here traces back to a cited file/test/command in those
documents — nothing here is a new finding.

## Overall completion assessment

Software Factory is a **real, working task-execution product for a single, narrow happy path** —
submit a natural-language instruction against a connected GitHub repo, and get a real git branch, a real
diff, and a real pull request — wrapped in a well-built, honest UI. Around that core, almost none of the
"AI-powered multi-agent software engineering platform" vision is built: there is no agent orchestration
layer, no multi-turn conversation, no test/quality/security integration, no RAG/document knowledge of any
kind, and only a thin, disconnected slice of the intended Repository Knowledge Graph. Rough estimate: the
**happy-path execution pipeline is roughly complete**; the **broader multi-agent, knowledge, and
governance vision is largely unbuilt** (single-digit percent of what the Decision Log describes).

## What is genuinely functional today

- Organizations, projects, RBAC, multi-tenant isolation, task/workflow management, WebSocket presence,
  cross-project dashboard — all real, backed by a passing test suite (112 passed / 4 honest
  environment-gated skips / 0 failures).
- A real end-to-end coding-agent happy path: natural-language task → real Git worktree clone → real file
  edits (when a local-CLI connection is used) → real `git diff` → real branch push → real GitHub PR, with
  honest degrade-to-failure (never a fabricated success) at every step.
- Six genuinely executable provider adapters (Claude Code, Codex, Gemini CLI, Qwen, Docker Sandbox,
  Custom) — all shell out to real binaries or make real HTTPS calls, nothing simulated.
- Real credential encryption at rest; real, verified Docker Sandbox isolation (network isolation and
  cancellation both proven against the live Docker daemon).
- A real diff viewer: the backend captures a genuine unified diff and the frontend parses it properly
  (not a mock renderer) into the newly-rebuilt 3-column Code Review workspace.

## What is only frontend or mocked

- **Approvals** screen — fully mocked, hardcoded fake decision history, no backend concept of an approval
  exists at all.
- **Knowledge Graph Explorer** / **Repository Intelligence** UI pages — both 100% `MockDataService`,
  never call the real (if thin) `/knowledge/*` backend that does exist.
- Two cosmetic "RAG" strings in mock data with zero backing logic.
- Agent capability labels are a static per-adapter list, not a real hierarchical role/capability schema.

## What is partially implemented

- Repository Knowledge Graph: real Neo4j connection and a genuinely-working sync/ingest/read path — but
  only 8 node labels, 7 relationship types, no schema constraints/indexes, no connection to the platform's
  real Git integration (it only reads an arbitrary local path), and a currently **empty** live graph.
- Audit logging: real backend writes, no frontend viewer.
- Agent lifecycle: simple 4-state status, no retry/escalation policy, no trace/telemetry.
- Recovery: "Restart" always re-runs from zero; there is no resume-from-checkpoint.

## What remains to be built

No agent-orchestration layer (Supervisor/Planner/Registry); no agent handoff/resume; no multi-turn task
conversation; no test execution; no quality/security scanning; no review comments; no RAG/document
knowledge system in any form; no Graph Access Service; no incremental/commit-aware Repository KG ingestion;
no provider routing/fallback/cost-tracking/execution-tracing; no notifications; no real human-approval gate.
Full detail and evidence for every item: `08-IMPLEMENTATION_GAP_ANALYSIS.md`.

## Most important architectural blockers

1. **Security defaults currently live, not just theoretical.** A passwordless dev-login bypass is
   *enabled* in this environment's `.env`, and the JWT secret / credential-encryption key are still their
   insecure placeholder defaults. This must be fixed before any deployment beyond a developer's own
   machine.
2. **No agent-orchestration layer exists.** Everything the product vision calls "multi-agent" today is a
   single adapter running a single prompt. This blocks handoff, collaboration, and routing/fallback work.
3. **No Graph Access Service.** Isolation for the one existing graph feature relies on caller discipline,
   not an enforced boundary — a real (if currently low-blast-radius) multi-tenancy gap.
4. **Sandboxing is inconsistent.** Only the dedicated Docker Sandbox adapter is actually isolated; the four
   LLM-CLI runtimes execute directly on the backend host.

## Current state of the Repository Knowledge Graph

Real but shallow and disconnected. Neo4j is genuinely wired up with working sync/ingest/read code — not
mocked — but it only extracts files and top-level classes/functions from an arbitrary local path (not a
connected Git repo), has no import/dependency/call/test relationships, no schema constraints, no
incremental updates, no commit-level snapshots, and the live graph currently holds **zero nodes**. No
coding agent ever queries it during execution. Full detail: `04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md`.

## Current state of autonomous coding-agent execution

Real for the single-shot, single-provider happy path; absent everywhere else. A task genuinely clones a
repo, lets a real CLI/API edit files, captures a real diff, and opens a real PR — and fails honestly
(never fabricating success) at every stage. But there is no planning phase, no approval gate, no multi-turn
conversation, no session resume, no test/quality/security verification of what the agent produced, and no
graph- or RAG-powered context beyond whatever the external CLI tool does on its own. "Autonomous" today
means "runs one instruction once," not "operates with ongoing judgment and verification."

## Five highest-priority next tasks

1. **Rotate/disable the live security defaults** (dev-login bypass, placeholder JWT/encryption secrets) —
   P0, immediate, no dependencies.
2. **Build the Graph Access Service** and add Neo4j schema constraints/indexes — before any further graph
   ingestion work widens an unguarded surface.
3. **Sandbox the four non-Docker coding-agent runtimes** using the isolation primitive that already works
   for Docker Sandbox.
4. **Wire Repository Knowledge Graph ingestion to the real Git integration** (not an arbitrary local path),
   recording commit SHAs — the prerequisite for everything else graph-related.
5. **Add real test execution**, wired into the Code Review workspace's already-built "Test Results" empty
   state — the single highest-leverage coding-workspace gap, since it's the first step toward agents that
   verify their own work rather than just producing a diff.

## Recommended next implementation phase

**Phase 0 (security hygiene) immediately, then Phase 2** as defined in
`09-SOFTWARE_FACTORY_REMAINING_ROADMAP.md`: Graph Access Service + Neo4j schema, sandboxing for all local-CLI
runtimes, and a minimal Agent Registry foundation. These are the foundational, currently-missing pieces
that every later phase (Repository KG depth, multi-turn conversation, agent orchestration, graph-powered
retrieval) depends on — building any of the more visible "wow" features first would be building on top of
gaps that later work would just have to come back and fix.

---

**Implementation has not started as a result of this audit and will not begin without the user's explicit
authorization.** All ten documents in this `audit/` folder are read-only findings produced without
modifying any application source file.
