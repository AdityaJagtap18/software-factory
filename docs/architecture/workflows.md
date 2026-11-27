# End-to-End Workflows

[← Back to README](../../README.md)

## Contents

- [Project Onboarding](#project-onboarding)
- [Single Task: Create → Execute → PR](#single-task-create--execute--pr)
- [Multi-Step Workflow Execution](#multi-step-workflow-execution)
- [Follow-Up Conversation on a Running/Completed Task](#follow-up-conversation-on-a-runningcompleted-task)
- [Agent Handoff on Failure](#agent-handoff-on-failure)
- [Repository Knowledge Sync](#repository-knowledge-sync)
- [Approval Gate](#approval-gate)

## Project Onboarding

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as Backend API
    participant GH as GitHub
    participant Neo as Neo4j

    User->>FE: Register / log in
    FE->>API: POST /auth/register or /auth/login
    API-->>FE: JWT access + refresh token
    User->>FE: Create organization
    FE->>API: POST /organizations
    User->>FE: Create project
    FE->>API: POST /projects
    User->>FE: Connect repository
    FE->>API: POST GitHub App installation flow
    API->>GH: Exchange installation for token, list repos
    User->>FE: Select repository
    FE->>API: POST /projects/{id}/repository-connections
    User->>FE: Sync knowledge graph
    FE->>API: POST /projects/{id}/knowledge/sync
    API->>Neo: ingest_repository() — real file/import extraction
    Neo-->>API: IngestResult
    API-->>FE: counts + commit SHA
```

## Single Task: Create → Execute → PR

This is the platform's core loop — adapted from the actual implementation in
[`task_execution.py`](../../backend/app/services/task_execution.py), not an idealized flow.

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant API as POST /projects/{id}/tasks
    participant Exec as task_execution.py
    participant Assign as agent_assignment.py
    participant WT as git_worktree.py
    participant Ctx as knowledge_context.py
    participant Safety as safety.py
    participant Adapter as Runtime Adapter
    participant Test as test_runner.py
    participant GH as GitHub
    participant Notif as notifications.py

    User->>FE: Fill New Task dialog<br/>(optionally pick a mock prompt template)
    FE->>API: POST tasks {title, description, connection_id?}
    API-->>FE: Task (status=not_started)
    User->>FE: Click Start
    FE->>API: POST /tasks/{id}/start
    API->>Exec: execute_task(task)
    Exec->>Assign: select_connection() if no connection set
    Exec->>WT: prepare_worktree(task, connection)
    WT-->>Exec: real local git checkout + branch
    Exec->>Ctx: build_task_knowledge_context()
    Ctx-->>Exec: relevant repo/project graph context
    Exec->>Safety: scan_prompt_for_injection(rag_context)
    Exec->>Adapter: execute(prompt, worktree_path)
    Adapter-->>Exec: ExecutionResult (output, usage, success)
    Exec->>WT: collect_diff()
    WT-->>Exec: real diff + changed files
    opt test files touched
        Exec->>Test: run_tests(worktree_path)
        Test-->>Exec: real pass/fail counts
    end
    opt diff is non-empty
        Exec->>WT: push_branch()
        WT->>GH: git push
        Exec->>GH: create pull request
        GH-->>Exec: PR url/number
    end
    Exec->>Safety: scan_output_for_secrets(output)
    Exec->>Notif: create_notification(task creator)
    Exec-->>API: Task (status=completed/failed)
    API-->>FE: updated Task
    Notif-->>FE: WebSocket push (if connected)
```

**Honesty notes baked into this flow (from the actual code, not assumption):** if no coding-agent
connection is reachable, the task fails with an explicit error rather than reporting success; if the
diff is empty, no PR is opened; if the adapter provides no usage data (every adapter except Ollama),
`usage` stays `{}` rather than being estimated.

## Multi-Step Workflow Execution

```mermaid
sequenceDiagram
    actor User
    participant API as POST /workflows/{id}/start
    participant Orch as workflow_execution.py
    participant StepN as Task (step N)
    participant StepM as Task (step N+1, depends on N)

    User->>API: start workflow
    API->>Orch: run_workflow() [background thread]
    Orch->>Orch: Round 1: steps with no unmet dependencies
    par concurrent, independent steps
        Orch->>StepN: execute (own thread, own DB session)
    end
    StepN-->>Orch: COMPLETED
    Orch->>Orch: Round 2: StepM now eligible<br/>(its dependency N is COMPLETED)
    Orch->>StepM: execute, with Workflow.shared_context<br/>folding in StepN's real output
    alt StepM fails and max_retries > 0
        Orch->>Orch: automatic TaskHandoff to next<br/>connection in fallback chain
        Orch->>StepM: resume (different adapter)
    end
    StepM-->>Orch: COMPLETED or FAILED
    Orch-->>API: Workflow COMPLETED (all steps ok)<br/>or FAILED (first genuine failure halts it)
```

A workflow using no `depends_on_step_orders` declarations runs byte-for-byte as a simple sequential
pipeline — this concurrency path is strictly additive, not a behavior change for workflows that don't
opt into it.

## Follow-Up Conversation on a Running/Completed Task

```mermaid
sequenceDiagram
    actor User
    participant API as POST /tasks/{id}/messages
    participant Exec as task_execution.py::execute_followup
    participant WT as git_worktree.py

    User->>API: "Also handle the empty-input case"
    API->>Exec: execute_followup(task, message)
    alt worktree still exists
        Exec->>WT: resume_worktree() — SAME branch/checkout
        WT-->>Exec: resumed real worktree
        Exec->>Exec: run adapter with full conversation history
        Exec-->>API: new AGENT TaskMessage + updated diff
    else no workspace to resume
        Exec-->>API: honest SYSTEM message explaining failure
    end
```

A follow-up while the task is already `running` is rejected with `409 Conflict` rather than racing a
second execution against the same worktree.

## Agent Handoff on Failure

```mermaid
sequenceDiagram
    actor Human
    participant API as POST /tasks/{id}/handoff
    participant HO as handoff.py
    participant WT as git_worktree.py
    participant AdapterB as New Adapter

    Note over Human,AdapterB: Connection A's attempt already failed mid-task
    Human->>API: request handoff to Connection B
    API->>HO: build_handover_package(task)
    HO->>HO: snapshot real git diff, output,<br/>test results, review comments, conversation
    HO-->>API: TaskHandoff row (immutable)
    API->>HO: resume_task_with_handoff()
    HO->>WT: resume_worktree() — same real branch
    WT-->>HO: resumed worktree, including A's real partial file changes
    HO->>AdapterB: execute(prompt built from handover package)
    AdapterB-->>HO: ExecutionResult
    HO-->>API: new TaskExecutionAttempt (Connection B)
```

## Repository Knowledge Sync

```mermaid
sequenceDiagram
    actor User
    participant API as POST /projects/{id}/knowledge/sync
    participant GAS as GraphAccessService
    participant Ing as code_ingestion.py
    participant Neo as Neo4j

    User->>API: trigger sync
    API->>GAS: ingest_repository(root_path)
    GAS->>Ing: walk files
    loop each file
        Ing->>Ing: pick LanguageAdapter (Python / TS-JS / unsupported→skip)
        Ing->>Ing: extract real imports
    end
    Ing->>Ing: compute_relationships()<br/>resolve DEPENDS_ON (same-repo imports)<br/>map TESTS (naming convention)
    Ing->>Neo: write File/Module nodes + edges,<br/>tag with real git commit SHA
    Neo-->>API: IngestResult (node/edge counts)
    API-->>User: sync summary
```

Incremental vs. full re-index: the ingestion walks and re-writes the current file set on each sync
call — there is no separate "full re-index" trigger distinct from "sync" in the current implementation;
a full re-index is simply running sync again, which recomputes relationships from the current file
state. Treat "incremental" language elsewhere as describing the per-file extraction granularity, not a
separate code path from full sync.

## Approval Gate

```mermaid
sequenceDiagram
    actor Agent as Task execution (automated)
    actor Reviewer
    participant API as /projects/{id}/approvals
    participant DB as Approval row

    Agent->>API: task reaches a state requiring approval<br/>(e.g. PR opened)
    API->>DB: create Approval (status=pending)
    Reviewer->>API: GET /approvals
    Reviewer->>API: POST /approvals/{id}/decide {approve|reject}
    API->>DB: update Approval status
```

**Scope note:** this is a post-hoc approval of an already-opened PR, not a pre-execution planning gate
— there is no `Plan` entity or "approve before the agent runs" step in the current implementation,
despite that being part of the original product vision (see
[`IMPLEMENTATION_STATE.md`](../../IMPLEMENTATION_STATE.md) Phase 3, P3-6).
