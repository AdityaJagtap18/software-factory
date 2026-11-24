# System Architecture

[← Back to README](../../README.md)

## Contents

- [Overview](#overview)
- [Complete System Diagram](#complete-system-diagram)
- [Frontend Architecture](#frontend-architecture)
- [Backend Architecture](#backend-architecture)
- [Request Lifecycle](#request-lifecycle)
- [External Integrations](#external-integrations)
- [Deployment Topology](#deployment-topology)

## Overview

Software Factory has no separate API-gateway service — FastAPI itself (`backend/app/main.py`) is the
single backend entry point, all routes mounted under `/api/v1`. There is one Angular SPA, one FastAPI
process, one PostgreSQL instance, one Neo4j instance, and the host filesystem used for real git
worktrees. This is a deliberately simple topology; there is no message queue, no separate worker
process, and no API gateway — orchestration runs as background threads inside the FastAPI process
itself (`workflow_execution.py`, `task_execution.py` spawn `threading.Thread`s for concurrent step
execution, not a separate task queue like Celery).

## Complete System Diagram

```mermaid
flowchart TB
    subgraph ClientLayer["Client Layer"]
        User["User (browser)"]
    end

    subgraph FrontendLayer["Frontend — Angular 18 SPA (frontend/)"]
        Router["App Router + authGuard"]
        Shell["AppShellComponent (sidebar, nav)"]
        Pages["Feature Pages<br/>(29 routes — dashboard, projects, tasks,<br/>workflows, knowledge, audit-log, ...)"]
        HttpClients["core/org/*.service.ts<br/>typed HttpClient wrappers"]
        Mock["MockDataService<br/>(agents/artifacts/code-review/<br/>monitoring/prompts/providers pages)"]
    end

    subgraph AuthLayer["Auth Layer"]
        JWT["JWT access token (60 min)<br/>+ hashed refresh-token Session row (30 day)"]
        RateLimit["core/rate_limit.py<br/>sliding-window limiter"]
    end

    subgraph BackendLayer["Backend — FastAPI (backend/app/)"]
        Routes["api/routes/*.py<br/>16 routers, prefix /api/v1"]
        Deps["api/deps.py<br/>get_current_user, require_org_member,<br/>require_project_access (RBAC)"]

        subgraph ServiceLayer["Service Layer (services/*.py)"]
            TaskExec["task_execution.py"]
            WorkflowExec["workflow_execution.py<br/>(round-based scheduler, threads)"]
            Handoff["handoff.py"]
            AgentAssign["agent_assignment.py"]
            GitWorktree["git_worktree.py"]
            GitSync["git_sync.py / git_webhook.py"]
            KnowledgeGraph["knowledge_graph.py"]
            GraphAccess["graph_access.py<br/>(mandatory project scoping)"]
            CodeIngestion["code_ingestion.py"]
            DocRetrieval["document_retrieval.py / embeddings.py"]
            Safety["safety.py"]
            Notifications["notifications.py<br/>(WebSocket manager)"]
            Audit["audit.py"]
        end

        subgraph RuntimeLayer["Agent Runtime (services/agent_runtime/)"]
            Registry["registry.py"]
            Adapters["adapters.py<br/>7 CodingAgentRuntimeAdapter impls"]
        end
    end

    subgraph DataLayer["Persistence"]
        PG[("PostgreSQL 16 + pgvector<br/>:5433")]
        Neo[("Neo4j 5<br/>:7688 bolt")]
        WTFS[("data/worktrees/<br/>real git checkouts")]
    end

    subgraph ExternalLayer["External Systems"]
        GitHubAPI["GitHub REST API + App webhooks"]
        AIProviders["Claude Code / Codex / Gemini / Qwen CLIs,<br/>Ollama HTTP, Docker daemon, Custom HTTP"]
    end

    User --> Router --> Shell --> Pages
    Pages --> HttpClients
    Pages -.mocked pages only.-> Mock
    HttpClients -->|HTTPS JSON| Routes
    HttpClients -->|WebSocket| Notifications
    HttpClients -->|Server-Sent Events| Routes

    Routes --> Deps
    Deps -->|validates| JWT
    Deps -->|login/register| RateLimit
    Deps --> ServiceLayer

    TaskExec --> GitWorktree
    TaskExec --> AgentAssign
    TaskExec --> Safety
    TaskExec --> RuntimeLayer
    WorkflowExec --> TaskExec
    WorkflowExec --> AgentAssign
    Handoff --> GitWorktree
    GraphAccess --> KnowledgeGraph
    CodeIngestion --> KnowledgeGraph
    DocRetrieval --> PG

    ServiceLayer --> PG
    GraphAccess --> Neo
    GitWorktree --> WTFS
    GitSync -->|REST| GitHubAPI
    WTFS -->|git clone/push| GitHubAPI
    Adapters -->|subprocess/HTTPS| AIProviders

    GitHubAPI -->|webhook POST /api/v1/webhooks/github| Routes
```

## Frontend Architecture

```mermaid
flowchart LR
    subgraph App["Angular App (standalone components, signals)"]
        Main["main.ts bootstrap"]
        Routes["app.routes.ts<br/>29 lazy-loaded routes"]
        Guard["auth.guard.ts<br/>redirects to /login if no token"]
        Shell["AppShellComponent<br/>sidebar nav, org switcher"]

        subgraph RealFeatures["Features backed by real APIs"]
            Dashboard["dashboard"]
            Projects["projects / project-workspace"]
            Tasks["task-workspace"]
            Workflows["workflows"]
            Knowledge["knowledge (graph)"]
            RepoIntel["repository-intelligence"]
            AuditLog["audit-log"]
            CodeReviewReal["code-review (comments/diff)"]
            Approvals["approvals"]
        end

        subgraph MockFeatures["Features using MockDataService (partly or fully)"]
            Agents["agents"]
            Artifacts["artifacts"]
            Monitoring["monitoring"]
            Prompts["prompts"]
            Providers["providers"]
            Settings["settings"]
        end

        subgraph CoreServices["core/org/*.service.ts"]
            TaskSvc["task.service.ts"]
            WorkflowSvc["workflow.service.ts"]
            KnowledgeSvc["knowledge.service.ts"]
            GitSvc["git-integration.service.ts"]
            NotifSvc["notification.service.ts"]
            AuditSvc["audit-log.service.ts"]
        end
    end

    Main --> Routes --> Guard --> Shell
    Shell --> RealFeatures
    Shell --> MockFeatures
    RealFeatures --> CoreServices
    CoreServices -->|HttpClient| Backend[("FastAPI /api/v1")]
```

Every component under `core/org/` is a thin typed wrapper over `HttpClient` calling a real backend
endpoint. `MockDataService` (`frontend/src/app/core/mock-data.service.ts`) is a single injectable
holding static signals of placeholder data, consumed directly by: `agents`, `artifacts`, `code-review`
(stats only — comments themselves are real), `monitoring`, `prompts`, `providers`, `settings`, and a
narrow slice of `project-workspace` (its Agents tab and Recent Activity feed, and the New Task dialog's
prompt-template picker).

## Backend Architecture

```mermaid
flowchart TB
    subgraph Entry["main.py"]
        FastAPIApp["FastAPI app"]
        Lifespan["lifespan: ensure_schema(), bind notification loop"]
        CORS["CORSMiddleware (settings.cors_origins)"]
    end

    subgraph Routers["16 routers mounted at /api/v1"]
        R1["auth"]; R2["organizations"]; R3["projects"]; R4["agent_runtimes"]
        R5["tasks"]; R6["workflows"]; R7["presence"]; R8["knowledge"]
        R9["dashboard"]; R10["git_integration"]; R11["approvals"]; R12["documents"]
        R13["orchestration"]; R14["notifications"]; R15["audit_log"]; R16["repository_intelligence"]
    end

    subgraph CrossCutting["Cross-cutting (api/deps.py, core/)"]
        Auth["get_current_user (JWT)"]
        RBAC["require_org_member / require_org_admin /<br/>require_project_access"]
        Config["core/config.py (Settings, SF_ env prefix)"]
        Security["core/security.py (hash/verify, JWT)"]
        RateLimiting["core/rate_limit.py"]
    end

    FastAPIApp --> Lifespan
    FastAPIApp --> CORS
    FastAPIApp --> Routers
    Routers --> Auth --> RBAC
    Routers --> Config
    Auth --> Security
    R1 --> RateLimiting
```

## Request Lifecycle

```mermaid
sequenceDiagram
    participant FE as Angular HttpClient
    participant MW as CORSMiddleware
    participant Route as api/routes/*.py
    participant Dep as api/deps.py
    participant Svc as services/*.py
    participant DB as PostgreSQL
    participant Neo as Neo4j (if applicable)

    FE->>MW: HTTPS request + Bearer JWT
    MW->>Route: forwarded (origin allowed)
    Route->>Dep: Depends(get_current_user)
    Dep->>DB: look up user from JWT subject
    Dep->>Route: User
    Route->>Dep: Depends(require_project_access)
    Dep->>DB: resolve ProjectMember role
    Dep-->>Route: ProjectContext(project, role)
    Route->>Svc: call with ProjectContext-scoped args
    Svc->>DB: read/write
    opt graph-touching operation
        Svc->>Neo: via GraphAccessService(ctx)
    end
    Svc-->>Route: result / raises HTTPException
    Route-->>FE: JSON response
```

## External Integrations

| System | Direction | Mechanism | Used for |
|---|---|---|---|
| GitHub | Outbound | REST API via GitHub App installation token | Repository listing, branch ops, PR creation (`git_provider/`, `git_integration.py`) |
| GitHub | Inbound | Webhook `POST /api/v1/webhooks/github` | `pull_request` and `check_suite` events keep `Task.git_pr_state`/`git_ci_status` in sync |
| Claude Code / Codex / Gemini CLI / Qwen | Outbound | Local subprocess (CLI installed on backend host) | Real coding-agent execution |
| Gemini (hosted) | Outbound | HTTPS API (`SF_GEMINI_API_KEY`) | Alternative to the Gemini CLI path |
| Ollama | Outbound | HTTP (`/api/generate`) | Local coding-agent execution + RAG embeddings (`nomic-embed-text`) |
| Docker daemon | Outbound | Docker SDK/CLI | `DockerSandboxAdapter` isolated execution; optional per-CLI sandbox images |
| Custom HTTP adapter | Outbound | User-configured HTTPS endpoint | Bring-your-own coding-agent backend |

## Deployment Topology

```mermaid
flowchart LR
    subgraph Compose["docker-compose.yml"]
        PG["postgres<br/>pgvector/pgvector:pg16<br/>:5433→5432"]
        N4["neo4j<br/>neo4j:5-community<br/>:7475→7474, :7688→7687"]
        BE["backend<br/>build ./backend<br/>:8020→8000<br/>alembic upgrade head && uvicorn"]
        FE["frontend<br/>build ./frontend (Nginx)<br/>:4300→80<br/>proxies /api/ → backend:8000"]
    end

    FE -->|depends_on: healthy| BE
    BE -->|depends_on: healthy| PG
    BE -->|depends_on: healthy| N4
    Browser["Browser"] -->|single origin :4300| FE
```

Local non-Docker development instead runs `ng serve` on `:4200` talking directly to `uvicorn` on
`:8010`, with Postgres still via `docker compose up -d postgres` on `:5433` and Neo4j likewise
containerized.
