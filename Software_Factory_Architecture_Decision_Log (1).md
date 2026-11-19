# Software Factory --- Architecture Decision & Design Log

**Document status:** Living architecture decision record\
**Prepared:** 19 November 2026\
**Product:** Multi-Tenant, Provider-Independent AI Software Factory\
**Source baseline:** `Software Factory.txt` supplied in the
conversation\
**Discussion coverage:** Domains 1–4 finalized; implementation-ready defaults recorded for Domains 5–8\
**Current status:** Architecture baseline consolidated; ready to begin Phase 0 / Phase 1 implementation

> **Purpose:** Preserve the architecture discussions, alternatives,
> rationales, approved decisions, component relationships and Mermaid
> diagrams in an editable Markdown document. This is a structured design
> log, not a verbatim transcript of every chat message. The diagrams are
> editable Mermaid source and may be rendered by compatible Markdown
> viewers.

------------------------------------------------------------------------

# 1. Document conventions and decision status

-   **Approved** means explicitly selected and finalized during the
    architecture discussion.
-   **Baseline** means present in the original `Software Factory.txt`
    specification.
-   **Proposed refinement** means a design refinement discussed during
    the conversation; it should not be mistaken for an already
    implemented feature.
-   **Open** means not yet decided.

This document distinguishes the original architecture baseline from
decisions made during the subsequent discussion. The decisions here are
design approvals, not evidence that implementation has already occurred.

# 2. Product vision and original architecture baseline

The Software Factory is an AI-powered engineering platform intended to
simulate and automate the operations of a software engineering
organization.

Users submit requirements, projects or GitHub issues. The factory turns
them into structured engineering tasks, assigns specialized agents,
executes work in isolated environments, validates the results and
delivers approved changes.

## 2.1 Core capabilities in the original specification

1.  Multi-tenant user and organization management.
2.  AI-powered requirements analysis and architecture planning.
3.  Multi-agent engineering workforce.
4.  Provider-independent agent execution.
5.  Parallel development and task dependency management.
6.  Agent failure recovery and provider handover.
7.  Git-based code and change management.
8.  Central prompt and artifact versioning.
9.  Repository intelligence using Neo4j.
10. Engineering knowledge graph using Neo4j.
11. Hybrid project and organization knowledge sharing.
12. Automated testing, security checks and code review.
13. Engineering observability and cost management.
14. Human approval and governance workflows.

## 2.2 Approved technology baseline

  -----------------------------------------------------------------------
  Area                    Technology              Responsibility
  ----------------------- ----------------------- -----------------------
  Frontend                Angular                 Factory user interface

  Backend/control plane   Python FastAPI          APIs and factory
                                                  services

  Agent orchestration     LangGraph               Agent reasoning and
                                                  state transitions

  Durable workflow        Temporal                Durable execution,
                                                  retries and recovery

  Transactional database  PostgreSQL              Authoritative factory
                                                  records

  Graph database          Neo4j                   Repository and
                                                  engineering knowledge

  Cache and messaging     Redis                   Caching, queues and
                                                  coordination

  Execution               Docker                  Isolated agent
                                                  environments

  Version control         Git / GitHub            Source code and
                                                  integration

  Prompt management       Central registry        Immutable prompt
                                                  versions

  Knowledge sharing       Hybrid                  Project-private and
                                                  approved organization
                                                  knowledge

  Artifact storage        S3-compatible object    Documents, reports and
                          storage                 execution artifacts

  Observability           OpenTelemetry +         Traces, metrics and LLM
                          Langfuse                observability

  Evaluation              Custom evaluation       Agent quality and
                          framework               execution reliability
  -----------------------------------------------------------------------

## 2.3 Original architectural principles

1.  **Factory-owned state:** The factory owns tasks, decisions,
    checkpoints, artifacts and execution history. Agents are replaceable
    workers.
2.  **Provider independence:** Business logic must not depend directly
    on a particular model provider.
3.  **Reproducibility:** Each execution records exact inputs, prompts,
    model configuration, Git state and knowledge snapshot.
4.  **Isolation:** Users, organizations, projects and execution
    environments have enforceable security boundaries.
5.  **Graphs are derived intelligence:** Neo4j is rebuildable from
    authoritative sources; graph failures must not corrupt canonical
    project data.
6.  **Human-controlled delivery:** Production changes, sensitive
    operations and final approvals require explicit authorization.

## 2.4 Original nine logical architecture layers

1.  Presentation --- Angular.
2.  Multi-tenant management.
3.  Factory control plane --- FastAPI, LangGraph and Temporal.
4.  Agent workforce --- Product, Architect, Planner, Backend, Frontend,
    Database, QA, Code Review and DevOps.
5.  Provider adapter.
6.  Execution environment --- Docker and Git.
7.  Engineering intelligence --- Repository Knowledge Graph and
    Engineering Knowledge Graph.
8.  Quality and verification.
9.  Data, observability and governance.

------------------------------------------------------------------------

# 3. Domain 1 --- Multi-User and Workspace Isolation

**Status: Design-level finalized**

The user approved a hybrid workspace ownership model, controlled
knowledge sharing and explicit execution visibility.

## 3.1 Final tenant and resource hierarchy

``` text
Software Factory
  └── Organization
       ├── Users and memberships
       ├── Organization policies and provider connections
       └── Projects
            ├── Project members and repositories
            ├── Project knowledge
            └── Workspaces
                 ├── Personal workspace
                 ├── Team-owned workspace
                 └── Tasks
                      └── Executions
                           ├── Isolated runtime
                           ├── Git branch/worktree
                           └── Logs, artifacts and results
```

Organization is the tenant boundary. Project is the shared engineering
boundary. Workspace is a logical context for work. Task is a unit of
work. Execution is an isolated, resumable runtime attempt.

## 3.2 Workspace ownership --- approved hybrid model

-   Personal workspaces are private by default.
-   Team-owned workspaces support shared logical collaboration.
-   A workspace is not a shared writable filesystem or shared Docker
    container.
-   Every execution receives its own isolated runtime and Git worktree.
-   Project knowledge is available to authorized project members.
-   Organization knowledge is shared only through controlled promotion
    and authorization.

## 3.3 Execution visibility --- explicit permission model

Execution visibility is permission-based; project membership alone does
not automatically grant access to every execution.

The proposed authorization combination is:

-   Organization-level RBAC.
-   Project-level roles and memberships.
-   Workspace membership.
-   Execution-specific access grants.
-   Resource-level authorization.

Initial roles discussed: Organization Admin, Project Admin, Developer,
Reviewer and Viewer.

API authorization, PostgreSQL Row-Level Security (RLS), graph-query
authorization and object-storage isolation must independently enforce
boundaries. Hiding an item in the UI is not an authorization control.

## 3.4 Execution lifecycle and membership changes

-   Execution lifecycle is independent of the initiating user's browser
    session or login session.
-   Work continues under factory identity after a user closes the
    browser or logs out.
-   Initiating user and attribution remain recorded.
-   When a user leaves an organization, project or workspace, their
    access is revoked.
-   Existing executions continue under factory identity, subject to
    policy.
-   Audit history is retained.
-   Revoking access to promoted knowledge prevents future retrieval;
    promotion provenance is retained.

## 3.5 Knowledge sharing

-   Project knowledge is private to the project by default.
-   Cross-project and organization-level sharing requires explicit
    promotion, validation and approval.
-   Secrets are excluded from promotion.
-   Ownership and provenance are retained.
-   A project must not gain access to another project's private
    knowledge merely because both projects belong to the same
    organization.

## 3.6 Proposed schema refinements for later data-model design

These were discussed as refinements, not confirmed existing tables:

-   `workspace_members`
-   `workspace_settings`
-   `execution_access`
-   `execution_artifacts`
-   `knowledge_promotions`
-   `knowledge_permissions`
-   `roles`
-   `permissions`
-   `role_permissions`

Existing baseline entities include organizations, users, memberships,
project members, invitations, projects, repositories, workspaces, tasks,
executions, artifacts and audit records.

## 3.7 Domain 1 decision register

  -----------------------------------------------------------------------
  ID                                  Approved decision
  ----------------------------------- -----------------------------------
  MU-01                               Multi-tenant organization
                                      architecture

  MU-02                               Users can belong to multiple
                                      organizations

  MU-03                               Projects support multiple users
                                      with different permissions

  MU-04                               Hybrid personal and team workspaces

  MU-05                               Workspaces are logical
                                      collaboration environments, not
                                      shared execution filesystems

  MU-06                               Every execution has isolated
                                      runtime resources

  MU-07                               Controlled project and organization
                                      knowledge sharing

  MU-08                               Explicit permission-based execution
                                      visibility

  MU-09                               Organization/project RBAC plus
                                      workspace/resource authorization

  MU-10                               PostgreSQL RLS plus independent
                                      graph and storage authorization

  MU-11                               Execution lifecycle is independent
                                      of user sessions

  MU-12                               Audit history is preserved
  -----------------------------------------------------------------------

## 3.8 Domain 1 architecture diagram --- multi-user isolation

``` mermaid
flowchart TB
    subgraph FACTORY["Software Factory"]
        subgraph ORGA["Organization A"]
            U1["User 1"]
            U2["User 2"]
            subgraph PROJA["Project A"]
                W1["Personal Workspace 1"]
                W2["Team Workspace"]
                T1["Task A"]
                T2["Task B"]
                E1["Isolated Execution 1"]
                E2["Isolated Execution 2"]
                W1 --> T1 --> E1
                W2 --> T2 --> E2
            end
        end
        subgraph ORGB["Organization B"]
            U3["User 3"]
            subgraph PROJB["Project B"]
                W3["Personal Workspace 3"]
                T3["Task C"]
                E3["Isolated Execution 3"]
                W3 --> T3 --> E3
            end
        end
    end
    U1 --> W1
    U2 --> W2
    U3 --> W3
```

## 3.9 Domain 1 architecture diagram --- shared project, separate executions

``` mermaid
flowchart LR
    subgraph PROJECT["Shared Project"]
        PRD["Shared PRD"]
        ARCH["Approved Architecture"]
        API["Approved API Contracts"]
        KNOW["Authorized Project Knowledge"]
    end

    subgraph USER1["User 1"]
        WS1["Personal Workspace"]
        EX1["Isolated Docker Execution"]
        G1["Git Worktree 1"]
        WS1 --> EX1 --> G1
    end

    subgraph USER2["User 2"]
        WS2["Team Workspace"]
        EX2["Isolated Docker Execution"]
        G2["Git Worktree 2"]
        WS2 --> EX2 --> G2
    end

    PRD --> EX1
    ARCH --> EX1
    API --> EX1
    KNOW --> EX1
    PRD --> EX2
    ARCH --> EX2
    API --> EX2
    KNOW --> EX2
```

------------------------------------------------------------------------

# 4. Domain 2 --- Multi-Agent Orchestration

**Status: Design-level finalized**

Domain 2 contains 32 approved decisions, OR-01 through OR-32. Four major
areas were finalized: orchestration topology, communication/state, task
decomposition/scheduling, and agent assignment/workers/provider routing.

## 4.1 Decision group 1 --- Orchestration topology

### Alternatives discussed

**A. Single central supervisor:** One supervisor coordinates every agent
directly. This is easy to audit and initially simpler, but can
accumulate too much coordination logic.

**B. Multiple specialized orchestrators:** Separate Product/Planning,
Engineering, Quality and Delivery orchestrators. This gives strong
domain separation but adds state-management and deployment complexity.

**C. Hybrid hierarchical orchestration --- approved:** A factory
supervisor coordinates a set of specialized LangGraph subgraphs.
Initially, these are modules within the same orchestration application,
not independently deployed microservices.

### Final topology

-   Temporal owns durable workflow lifecycle, retries, timers and
    recovery.
-   One factory supervisor coordinates each factory workflow.
-   LangGraph subgraphs coordinate specialized domains.
-   PostgreSQL stores canonical factory records.
-   Multiple project workflows can execute concurrently.
-   Agent workers can be shared infrastructure, subject to tenant and
    execution isolation.

### Diagram: hybrid hierarchical orchestration

``` mermaid
flowchart TB
    USER["User / Project Request"]
    TEMP["Temporal - Durable Workflow"]
    ROOT["Factory Supervisor - LangGraph"]

    USER --> TEMP --> ROOT

    ROOT --> PRODUCT["Product Subgraph"]
    ROOT --> ARCH["Architecture Subgraph"]
    ROOT --> DEV["Engineering Subgraph"]
    ROOT --> QUALITY["Quality Subgraph"]
    ROOT --> DELIVERY["Delivery Subgraph"]

    PRODUCT --> PA["Product / Planning Agents"]
    ARCH --> AA["Architect Agent"]
    DEV --> EA["Backend / Frontend / Database Agents"]
    QUALITY --> QA["QA / Review Agents"]
    DELIVERY --> DA["DevOps Agent"]

    PRODUCT --> ROOT
    ARCH --> ROOT
    DEV --> ROOT
    QUALITY --> ROOT
    DELIVERY --> ROOT
    ROOT --> TEMP
```

### Diagram: concurrent project workflows

``` mermaid
flowchart TB
    subgraph SHARED["Shared Factory Infrastructure"]
        WORKERS["Agent Worker Pool"]
        PROVIDERS["Provider Adapters"]
    end

    subgraph A["Organization A - Project A"]
        TA["Temporal Workflow A"]
        SA["Supervisor A"]
        TA --> SA
    end

    subgraph B["Organization B - Project B"]
        TB["Temporal Workflow B"]
        SB["Supervisor B"]
        TB --> SB
    end

    subgraph C["Organization A - Project C"]
        TC["Temporal Workflow C"]
        SC["Supervisor C"]
        TC --> SC
    end

    SA --> WORKERS
    SB --> WORKERS
    SC --> WORKERS
    WORKERS --> PROVIDERS
```

## 4.2 Decision group 2 --- Agent communication and shared state

### Alternatives discussed

1.  **Direct agent-to-agent communication:** Natural collaboration, but
    unrestricted messaging creates coupling, loops, difficult auditing
    and unclear authority.
2.  **Shared workflow state:** Agents consume structured information
    from a shared, versioned context. Requires ownership and concurrency
    controls.
3.  **Event-based communication:** Components publish events such as
    `APIContractPublished`, `BackendImplementationCompleted`,
    `TestsCompleted` and `ReviewRejected`. Supports decoupling but
    requires idempotency and recovery.
4.  **Task contracts and structured handovers:** Each agent receives an
    explicit assignment and returns structured outputs. Supports
    reproducibility and provider handover.

### Final approved model

Controlled combination of all four mechanisms:

-   Shared state is the primary collaboration context.
-   Task contracts define inputs, responsibilities and outputs.
-   Events signal meaningful workflow changes.
-   Direct communication is restricted and mediated by the supervisor or
    communication service.

### State ownership

  -----------------------------------------------------------------------
  Component                           Owns
  ----------------------------------- -----------------------------------
  Temporal                            Durable workflow lifecycle and
                                      history

  Factory Supervisor                  Delegation decisions and workflow
                                      transitions

  Execution State Manager             Validated state updates and version
                                      management

  Individual agent                    Its assigned task outputs and
                                      execution results

  PostgreSQL                          Canonical factory business and
                                      execution records

  Redis                               Event transport and transient
                                      coordination

  Neo4j                               Derived repository and engineering
                                      knowledge projections

  LangGraph                           Active reasoning and coordination
                                      state
  -----------------------------------------------------------------------

LangGraph state is not the permanent database. PostgreSQL is canonical
for factory business and execution records. Temporal maintains its
durable workflow history. Redis is not the sole store for critical
events.

### Concurrency and state rules

1.  Single-writer ownership: every task and artifact has an
    authoritative owner.
2.  Versioned updates: every update identifies the version on which it
    is based.
3.  Optimistic concurrency: conflicting updates are rejected and
    reconciled rather than silently overwriting newer state.
4.  Published outputs and approved contracts are versioned.
5.  Event consumers are idempotent.
6.  Dependencies must be satisfied before downstream work starts.
7.  Clarification requests are mediated and important decisions are
    recorded.

### Diagram: controlled communication

``` mermaid
flowchart TB
    SUP["Factory Supervisor - LangGraph"]
    CONTRACT["Versioned Task Contracts"]
    STATE["Execution State Manager"]
    EVENTS["Transactional Event System"]
    AGENTS["Specialized Agent Workers"]

    PG[("PostgreSQL")]
    OUTBOX["Transactional Outbox"]
    REDIS["Redis Event Transport"]
    TEMP["Temporal Workflow"]

    SUP --> CONTRACT
    CONTRACT --> AGENTS
    AGENTS --> STATE
    STATE --> PG
    STATE --> EVENTS
    EVENTS --> OUTBOX
    OUTBOX --> REDIS
    REDIS --> TEMP
    TEMP --> SUP

    SUP <-->|"Restricted clarification"| AGENTS
```

### Example structured state

``` json
{
  "project_id": "project-101",
  "task_id": "task-201",
  "requirements": {
    "objective": "Build supplier risk dashboard"
  },
  "architecture": {
    "backend": "Spring Boot",
    "frontend": "Angular",
    "database": "PostgreSQL"
  },
  "api_contract": {
    "status": "approved",
    "version": "1.0"
  },
  "agent_outputs": {},
  "task_status": "in_progress"
}
```

### Example task handover contract

**Input:** Task objective, architecture specification, API contract
version, database schema reference, acceptance criteria and relevant
repository context.

**Expected output:** Implementation summary, files changed, Git
branch/commit reference, tests executed, test results, known issues and
remaining work.

## 4.3 Decision group 3 --- Task decomposition, DAGs and parallel execution

### Alternatives discussed

-   **Static decomposition:** Planner creates the full DAG before
    execution. Predictable but less adaptable.
-   **Dynamic decomposition:** Agents create tasks as they discover
    work. Flexible but risks task explosion, uncontrolled dependencies
    and poor estimates.
-   **Hybrid decomposition --- approved:** Planner creates the initial
    DAG. Agents may propose additional tasks. Supervisor validates
    proposals before they become executable.

### Final task lifecycle

``` mermaid
flowchart TD
    A["User Requirement"]
    B["Planner Agent"]
    C["Initial Task DAG"]
    D["Supervisor Validation"]
    E{"DAG Approved?"}
    F["Revise Plan"]
    G["Scheduler"]
    H["Ready Task Queue"]
    I["Agent Execution"]
    J["Output Verification"]
    K{"Accepted?"}
    L["Mark Task Complete"]
    M["Retry / Rework"]
    N["Task Proposal"]
    O{"Supervisor Approves?"}
    P["New DAG Version"]

    A --> B --> C --> D --> E
    E -->|No| F --> B
    E -->|Yes| G --> H --> I --> J --> K
    K -->|Yes| L --> G
    K -->|No| M --> G
    I --> N
    N --> O
    O -->|Yes| P --> G
    O -->|No| I
```

### Example engineering DAG

``` mermaid
flowchart TD
    A["Analyze Requirements"]
    B["Design Architecture"]
    C["Design Database Schema"]
    D["Define API Contracts"]
    E["Backend Implementation"]
    F["Frontend Implementation"]
    G["ML Integration"]
    H["Integration"]
    I["QA and Testing"]
    J["Code Review"]
    K["Delivery Approval"]

    A --> B
    B --> C
    B --> D
    C --> E
    D --> E
    D --> F
    B --> G
    E --> H
    F --> H
    G --> H
    H --> I
    I --> J
    J --> K
```

### Scheduler rules

The scheduler evaluates:

1.  Dependency readiness.
2.  Task priority.
3.  Agent capability and availability.
4.  CPU, memory, GPU and provider quotas.
5.  Git and workspace isolation.
6.  Organization/project fairness and resource limits.

### Parallel execution rules

-   Independent tasks may execute concurrently.
-   Tasks sharing approved inputs may run concurrently.
-   A task waits for mandatory dependencies.
-   Separate worktrees prevent shared-directory collisions, but do not
    eliminate Git merge conflicts.
-   Integration coordinator detects conflicts, rebases, tests and
    escalates.
-   Failed tasks can be retried or reassigned without losing original
    attempt history.

### DAG versioning and recovery

-   Each approved DAG has a version.
-   Adding tasks or changing dependencies creates a new DAG version.
-   Running tasks retain pinned input contracts unless explicitly
    replanned.
-   A retry or provider handover creates a new attempt linked to the
    canonical task.
-   Original attempts remain immutable.

### Task record example

``` json
{
  "task_id": "TASK-104",
  "project_id": "PROJECT-101",
  "dag_version": 3,
  "title": "Implement supplier API",
  "agent_role": "backend",
  "status": "ready",
  "priority": "high",
  "dependencies": ["TASK-102", "TASK-103"],
  "input_contract": {
    "architecture_version": 1,
    "api_contract_version": 1
  },
  "acceptance_criteria": [
    "API follows approved contract",
    "Unit tests pass",
    "Authentication is enforced"
  ],
  "execution_constraints": {
    "isolated_worktree": true,
    "network_access": "restricted"
  }
}
```

### Task lifecycle states

Proposed states: Proposed, Validated, Ready, Assigned, Running,
Completed, Verified, Blocked, Failed, Cancelled, Awaiting Approval and
Retry.

A task is not complete merely because an agent reports completion.
Required acceptance criteria and verification checks must pass.

### Concurrency controls

Configurable limits at organization, project, provider and execution
levels. Additional controls include optimistic locking, idempotency
keys, execution leases/ownership, bounded retries with backoff,
timeouts, cancellation and reconciliation.

### Diagram: scheduler and execution

``` mermaid
flowchart TD
    A["Versioned Task DAG"]
    B["Dependency Evaluator"]
    C["Ready Task Queue"]
    D["Scheduler"]
    E["Capability and Resource Check"]
    F{"Resources available?"}
    G["Assign Agent"]
    H["Create Isolated Execution"]
    I["Execute Task"]
    J["Validate Output"]
    K["Persist Result and Emit Event"]
    L["Refresh DAG and Ready Queue"]
    M["Wait / Retry"]

    A --> B --> C --> D --> E --> F
    F -->|Yes| G --> H --> I --> J --> K --> L --> B
    F -->|No| M --> D
```

## 4.4 Decision group 4 --- Agent assignment, worker pools and provider routing

### Agent assignment alternatives

-   Fixed role assignment: simplest but inflexible.
-   Fully dynamic capability matching: flexible but requires more
    complex eligibility and ranking.
-   **Hybrid assignment --- approved:** First filter by role, then match
    capabilities.

### Final assignment flow

``` mermaid
flowchart TD
    A["Ready Task"]
    B["Identify Required Role"]
    C["Filter Agent Registry"]
    D["Check Skills and Tools"]
    E["Check Permissions and Provider Compatibility"]
    F["Check Availability and Resources"]
    G["Rank Eligible Agents"]
    H["Assign Agent"]
    I["Record Assignment"]

    A --> B --> C --> D --> E --> F --> G --> H --> I
```

### Agent Registry

The registry describes agent definitions, not necessarily running
processes.

Suggested metadata:

-   Agent ID and version.
-   Role.
-   Skills and supported task types.
-   Tools.
-   Required permissions.
-   Supported provider/model capabilities.
-   Resource requirements.
-   Evaluation history.
-   Availability or worker eligibility.

Hard eligibility checks (required capabilities, permissions, tools and
policy) happen before ranking. Ranking can consider suitability,
availability, verified evaluation history and cost.

If no eligible agent is available, the task waits or is escalated. The
system must not silently assign an unqualified agent.

### Worker-pool alternatives

-   One shared pool: simplest, but workload classes compete.
-   Dedicated pool for every agent role: independently scalable but
    operationally expensive.
-   **Hybrid logical pools --- approved:** Workload-oriented queues on
    shared worker infrastructure.

Approved logical pools:

  -----------------------------------------------------------------------
  Pool                                Workloads
  ----------------------------------- -----------------------------------
  Planning and Analysis               Requirements, architecture,
                                      planning, documentation

  Engineering                         Backend, frontend, database and
                                      application development

  Quality                             Testing, code review, security and
                                      verification

  Heavy Compute                       ML training, GPU inference and
                                      resource-intensive workloads
  -----------------------------------------------------------------------

Initially these are logical queues/configurations, not separate
microservices. Dedicated deployments may be introduced when scale,
resource or isolation requirements justify them.

### Agent, worker and execution distinction

-   Agent definition: what the agent is capable of doing.
-   Worker: runtime process that claims and executes work.
-   Execution environment: isolated container, filesystem and Git
    worktree used for the task.

### Worker-pool diagram

``` mermaid
flowchart TB
    S["Factory Scheduler"]
    S --> P["Planning / Analysis Queue"]
    S --> C["Engineering Queue"]
    S --> Q["Quality Queue"]
    S --> H["Heavy Compute Queue"]

    P --> W["Shared Worker Infrastructure"]
    C --> W
    Q --> W
    H --> W

    W --> E1["Isolated Execution 1"]
    W --> E2["Isolated Execution 2"]
    W --> E3["Isolated Execution 3"]
    W --> E4["Isolated Execution 4"]
```

### Provider routing alternatives

-   Fixed provider per agent: simple but limits flexibility.
-   Capability-based routing: flexible but can ignore organizational
    constraints if policy is not first.
-   **Policy-first capability-based routing with controlled fallback ---
    approved.**

Final routing sequence:

1.  Check organization-approved providers.
2.  Check task-specific model capabilities.
3.  Check provider availability and quotas.
4.  Rank eligible models using quality, latency and cost.
5.  Select provider/model.
6.  Execute through a common provider adapter.
7.  Record configuration and outcome.

Fallback is permitted only to organization-approved alternatives. If a
tenant allows only one provider, the factory cannot silently switch to
another.

### Provider-routing diagram

``` mermaid
flowchart TD
    A["Agent Task"]
    B["Provider Router"]
    C["Organization Provider Policy"]
    D["Task Capability Requirements"]
    E["Provider Availability and Quotas"]
    F["Cost / Latency / Quality Ranking"]
    G["Select Eligible Model"]
    H["Provider Adapter"]
    I["Claude / Gemini / OpenAI / Ollama"]
    J["Persist Execution Configuration"]

    A --> B --> C --> D --> E --> F --> G --> H --> I
    G --> J
```

### Illustrative provider adapter interface

``` python
class ProviderAdapter:

    def generate(self, request):
        ...

    def stream(self, request):
        ...

    def execute_tool(self, request):
        ...

    def get_capabilities(self):
        ...
```

This is an illustrative common interface. Provider-specific adapters
translate the common request into each provider's API. Coding-agent
runtimes may require a broader runtime interface; that question remains
for Domain 3.

## 4.5 Domain 2 consolidated architecture diagram

``` mermaid
flowchart TB
    USER["User Requirement"]
    TEMP["Temporal - Durable Workflow"]
    SUP["Factory Supervisor - LangGraph"]

    subgraph PLAN["Planning and Coordination"]
        PL["Planner Agent"]
        DAG["Versioned Task DAG"]
        SCH["Task Scheduler"]
        REG["Agent Registry"]
        MATCH["Role and Capability Matcher"]
    end

    subgraph COMM["Controlled Agent Communication"]
        CONTRACT["Task Contracts"]
        STATE["Versioned Shared State"]
        EVENT["Transactional Events"]
    end

    subgraph WORKERS["Hybrid Worker Pools"]
        PW["Planning Pool"]
        EW["Engineering Pool"]
        QW["Quality Pool"]
        HW["Heavy Compute Pool"]
    end

    subgraph EXEC["Isolated Execution"]
        DOCKER["Docker Environments"]
        GIT["Git Branches / Worktrees"]
        TOOLS["Authorized Tools"]
    end

    subgraph PROVIDERS["Provider Routing"]
        ROUTER["Policy-first Provider Router"]
        ADAPTER["Common Provider Adapter"]
        MODELS["Claude / Gemini / OpenAI / Ollama"]
    end

    PG[("PostgreSQL - Canonical Records")]
    REDIS["Redis - Event Transport"]
    NEO[("Neo4j - Engineering Knowledge")]

    USER --> TEMP --> SUP
    SUP --> PL --> DAG --> SCH
    SCH <--> REG
    SCH --> MATCH
    MATCH --> CONTRACT
    CONTRACT --> PW
    CONTRACT --> EW
    CONTRACT --> QW
    CONTRACT --> HW

    PW --> DOCKER
    EW --> DOCKER
    QW --> DOCKER
    HW --> DOCKER

    DOCKER --> GIT
    DOCKER --> TOOLS
    DOCKER <--> ROUTER
    ROUTER --> ADAPTER --> MODELS

    DOCKER --> STATE
    STATE --> PG
    STATE --> EVENT
    EVENT --> REDIS
    REDIS --> TEMP

    NEO --> SUP
    PG --> SUP
```

## 4.6 Complete Domain 2 decision register

### OR-01 to OR-05 --- Orchestration topology

  -----------------------------------------------------------------------
  ID                                  Approved decision
  ----------------------------------- -----------------------------------
  OR-01                               Hybrid hierarchical orchestration

  OR-02                               Temporal owns durable workflow
                                      lifecycle

  OR-03                               One factory supervisor per workflow

  OR-04                               Specialized LangGraph subgraphs
                                      coordinate agent domains

  OR-05                               Subgraphs initially run within the
                                      same orchestration application
  -----------------------------------------------------------------------

### OR-06 to OR-13 --- Communication and state management

  -----------------------------------------------------------------------
  ID                                  Approved decision
  ----------------------------------- -----------------------------------
  OR-06                               Controlled combination of shared
                                      state, contracts, events and
                                      restricted direct communication

  OR-07                               PostgreSQL is canonical for factory
                                      business and execution records

  OR-08                               LangGraph manages active
                                      coordination state

  OR-09                               Temporal owns durable workflow
                                      history and lifecycle

  OR-10                               Task contracts and outputs are
                                      versioned

  OR-11                               State updates enforce ownership and
                                      concurrency validation

  OR-12                               Transactional outbox and idempotent
                                      event processing

  OR-13                               Direct agent communication is
                                      restricted and mediated
  -----------------------------------------------------------------------

### OR-14 to OR-22 --- Task decomposition and scheduling

  -----------------------------------------------------------------------
  ID                                  Approved decision
  ----------------------------------- -----------------------------------
  OR-14                               Hybrid decomposition: initial DAG
                                      plus approved dynamic expansion

  OR-15                               Supervisor validates DAG changes

  OR-16                               Dependency-aware scheduling

  OR-17                               Capability- and resource-aware
                                      scheduling

  OR-18                               Independent tasks may execute
                                      concurrently

  OR-19                               Versioned DAG and pinned task
                                      inputs

  OR-20                               Isolated Git worktrees and
                                      coordinated integration

  OR-21                               Configurable organization, project,
                                      provider and execution limits

  OR-22                               Retries and recovery preserve
                                      execution history
  -----------------------------------------------------------------------

### OR-23 to OR-32 --- Assignment, workers and providers

  -----------------------------------------------------------------------
  ID                                  Approved decision
  ----------------------------------- -----------------------------------
  OR-23                               Role filtering followed by
                                      capability matching

  OR-24                               Central Agent Registry

  OR-25                               Permission and capability checks
                                      before assignment

  OR-26                               Assignment decisions and history
                                      are recorded

  OR-27                               Hybrid logical worker pools on
                                      shared infrastructure

  OR-28                               Isolated Docker execution per
                                      assigned task

  OR-29                               Provider selection is policy-first
                                      and capability-based

  OR-30                               Provider fallback is restricted to
                                      approved alternatives

  OR-31                               Common provider adapter interface

  OR-32                               Provider/model configuration is
                                      recorded per execution attempt
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 5. Consolidated technology responsibility map

  Technology                     Responsibility
  ------------------------------ -----------------------------------------------
  Angular                        Factory user interface
  FastAPI                        API, authorization and control-plane services
  LangGraph                      Supervisor, planning and agent coordination
  Temporal                       Durable workflow execution and recovery
  PostgreSQL                     Canonical factory state and records
  Redis                          Event transport and transient coordination
  Neo4j                          Repository and engineering knowledge graph
  Docker                         Isolated agent execution
  Git/GitHub                     Version control and integration
  Provider adapters              Standardized model-provider integration
  OpenTelemetry                  Distributed operational tracing
  Langfuse                       LLM traces and observability
  Custom evaluation framework    Agent and output quality evaluation
  S3-compatible object storage   Immutable artifacts and documents
  Central prompt registry        Versioned, governed prompts

# 6. Important architecture boundaries

These boundaries were repeatedly emphasized and should remain explicit
in future design work:

1.  Temporal is the durable workflow engine; LangGraph is the agent
    reasoning/orchestration engine.
2.  PostgreSQL is the canonical store for factory business and execution
    records; LangGraph's active state is not a replacement database.
3.  Redis transports events and supports transient coordination; it is
    not the only durable record of critical events.
4.  Neo4j is a derived knowledge projection, not the canonical source of
    transactional truth.
5.  Agent definitions, worker processes and execution environments are
    distinct concepts.
6.  Agent identity is independent of model provider.
7.  Provider sessions are replaceable; canonical task state is not.
8.  Team workspaces are logical collaboration boundaries, not shared
    writable execution environments.
9.  Separate Git worktrees reduce shared-directory collisions but do not
    replace merge conflict detection.
10. Agent-proposed tasks do not become executable until the supervisor
    validates them.
11. Human authorization remains necessary for sensitive delivery and
    governance actions.

# 7. Open items and next architecture domain

## 7.1 Domain 3 --- Provider Integration

**Status: Finalized. Decisions PI-01 through PI-50 approved.**

### Decision 1 --- Unified Agent Runtime

**Approved:** One common Agent Runtime Interface with two specialized
adapter families:

- LLM provider adapters for model APIs such as Claude, Gemini, OpenAI
  and Ollama.
- Coding-agent runtime adapters for coding-agent products such as
  Codex, Claude Code and Gemini CLI.

The common lifecycle interface includes capability discovery, start,
stream, status, result retrieval, cancellation, recovery, health checks
and usage reporting. Runtime-specific behavior remains behind each
adapter. Unsupported operations must be reported explicitly.

### Decision 2 --- Capability normalization

**Approved:** A hierarchical normalized capability schema with
provider-specific extensions.

Capability profiles distinguish four layers:

1. Model capabilities.
2. Adapter capabilities.
3. Agent-runtime capabilities.
4. Execution-environment capabilities.

Profiles include constraints, model/runtime identifiers, schema
versioning, validation provenance and timestamps. Validation levels are
Declared, Tested and Verified. Mandatory task requirements are hard
filters; preferences are ranking criteria; organization policy takes
precedence. Each execution pins the capability profile version used.

### Decision 3 --- Coding-agent execution and integration

**Approved:** Hybrid isolated execution with resumable task context.

- Each execution attempt receives a dedicated Docker container.
- Each task uses an isolated Git branch/worktree.
- Git state, checkpoints, logs, artifacts and execution manifests are
  persisted outside the container.
- Native coding-agent session resume may be used when supported, but is
  an optimization and never the sole recovery mechanism.
- Factory-owned state reconstructs work in a replacement attempt.
- Retries create new immutable attempts; they do not overwrite history.
- Filesystem, terminal, network, Git and resource permissions are
  explicitly restricted.

### Decision 4 --- Credential management and provider security

**Approved:** Hybrid credential architecture with PostgreSQL metadata,
an external secrets manager for secret values and a Credential Broker
for scoped runtime injection.

- Credential ownership supports organization, user and project scopes,
  subject to organization policy.
- PostgreSQL stores metadata and references, not plaintext secret values.
- The secrets manager stores API keys, OAuth tokens and other sensitive
  authentication material.
- The Credential Broker authorizes access using tenant, project, task,
  runtime and provider context.
- Executions receive only the minimum required credential access.
- Credential expiry, rotation, revocation, redaction and audit are
  explicitly managed.
- Provider-specific authentication is implemented by the relevant
  adapter; generic authentication assumptions are not made.
- Provider endpoints and local runtime network access are governed by
  policy.

### Decision 5 --- Provider fallback and context reconstruction

**Approved:** Policy-controlled fallback with versioned handover.

- Retry the same provider for transient failures using bounded retries
  and backoff where appropriate.
- Organization policy controls approved fallback candidates.
- Capability, security, data-handling, credential, quota and budget
  compatibility are mandatory checks before switching.
- Handover packages preserve task context, pinned inputs, decisions,
  progress, Git state, artifacts, logs and validation evidence.
- Replacement attempts reconstruct from factory-owned state rather than
  depending on private provider reasoning or native session state.
- Provider switching creates a new immutable execution attempt.
- If no safe alternative exists, pause and escalate.

### Decision 6 --- Model configuration and version pinning

**Approved:** Central Model Configuration Registry with controlled
task-level overrides, strict version pinning and organization-policy
authorization.

- Model profiles are centrally registered, immutable once published
  and versioned; changes create new versions.
- Organizations define approved profiles and policies.
- Projects and tasks select approved profiles.
- Task-level overrides are permitted only when organization policy
  authorizes the role, task type and requested changes.
- Every execution manifest pins the selected profile ID and version,
  requested model identifier, resolved model identifier/version where
  exposed, inference parameters, tool schema version, capability
  profile version and configuration hash.
- Existing tasks and retries retain their pinned configuration unless
  an explicitly authorized change is recorded.
- If fallback requires a different provider or model configuration,
  the replacement configuration is separately validated, versioned
  and recorded with its reason and relationship to the original.
- Model profiles contain no secrets; credential references are resolved
  through the Credential Broker.
- Provider aliases and rolling model versions are recorded with the
  resolved identifier and observation time where available. Exact output
  reproducibility is not guaranteed when providers do not expose
  immutable model revisions.

### Domain 3 decision register

| ID | Finalized decision |
|---|---|
| PI-01 | One common Agent Runtime Interface |
| PI-02 | Separate LLM and coding-agent adapter families |
| PI-03 | Runtime-specific capabilities and lifecycle behavior remain supported |
| PI-04 | Runtime implementations are registered and versioned |
| PI-05 | Hierarchical normalized capability schema |
| PI-06 | Provider-specific capability extensions |
| PI-07 | Separate model, adapter, runtime and environment capabilities |
| PI-08 | Declared, Tested and Verified validation levels |
| PI-09 | Capability profiles are versioned |
| PI-10 | Mandatory requirements are hard filters; preferences are ranking criteria |
| PI-11 | Executions pin the selected capability profile |
| PI-12 | Docker isolation per execution attempt |
| PI-13 | Git state and checkpoints persist outside containers |
| PI-14 | Native session resume is an optimization, not a dependency |
| PI-15 | Factory-owned state enables runtime-independent recovery |
| PI-16 | Retries create new immutable execution attempts |
| PI-17 | Tool permissions and container resources are explicitly restricted |
| PI-18 | Hybrid credential architecture: PostgreSQL metadata, external secrets manager and Credential Broker |
| PI-19 | Organization, user and project credential ownership scopes |
| PI-20 | Organization policy governs permitted credential scopes and provider access |
| PI-21 | Credential Broker authorizes scoped runtime injection |
| PI-22 | Secrets are excluded from prompts, Git commits and ordinary logs |
| PI-23 | Credential rotation, expiry and revocation are explicitly managed |
| PI-24 | Provider-specific authentication is implemented by the relevant adapter |
| PI-25 | Credential access and administrative changes are audited |
| PI-26 | Policy-controlled provider fallback |
| PI-27 | Retry the same provider for transient failures before switching where appropriate |
| PI-28 | Organization policy controls approved fallback candidates |
| PI-29 | Capability and security compatibility are mandatory fallback checks |
| PI-30 | Versioned handover packages preserve task context and execution evidence |
| PI-31 | Provider switching creates a new immutable execution attempt |
| PI-32 | Replacement attempts reconstruct context from factory-owned state |
| PI-33 | Credentials are reauthorized through the Credential Broker |
| PI-34 | Cost, quota and execution constraints are checked before fallback |
| PI-35 | If no safe alternative exists, pause and escalate |
| PI-36 | Central Model Configuration Registry with controlled task-level overrides |
| PI-37 | Published model profiles are immutable and versioned |
| PI-38 | Strict version pinning is applied to tasks and execution attempts |
| PI-39 | Task-level overrides are authorized by organization policy |
| PI-40 | Execution manifests pin profile, model, runtime-relevant configuration and capability versions |
| PI-41 | Fallback configuration changes are separately validated and explicitly recorded |

### Decision 7 --- Provider observability, evaluation, cost and reliability

**Approved:** Layered observability and evaluation architecture, hybrid
evaluation strategy and advisory routing influence.

- OpenTelemetry provides operational telemetry across workflows,
adapters and execution environments.
- Langfuse provides LLM tracing and model-interaction visibility.
- The custom evaluation framework provides engineering-quality, cost,
reliability and provider-comparison analytics.
- Evaluation combines deterministic automated checks, LLM-based
assessments and human review.
- Provider comparisons are segmented by agent role and task category,
with evaluation dataset/version, evaluator version, time period and
sample count retained as comparison context.
- Provider performance initially produces advisory recommendations;
it does not independently change routing.
- Routing remains subject to organization policy, capability, security,
credential, budget and quota constraints.
- Any authorized model/provider change must create an explicit,
auditable configuration record. Existing pinned configurations are not
silently changed.

Operational telemetry and output-quality evaluation remain distinct
measurement sources and are correlated using canonical task and
execution identifiers.

### Domain 3 decision register additions

| ID | Finalized decision |
|---|---|
| PI-42 | Layered observability and evaluation architecture |
| PI-43 | OpenTelemetry for operational telemetry |
| PI-44 | Langfuse for LLM tracing |
| PI-45 | Custom evaluation framework for quality, cost and reliability analytics |
| PI-46 | Hybrid evaluation: automated checks, LLM-based evaluation and human review |
| PI-47 | Provider comparisons segmented by agent role and task category |
| PI-48 | Provider scorecards retain sample counts and evaluation provenance |
| PI-49 | Provider performance initially influences routing through advisory recommendations |
| PI-50 | Routing remains policy-controlled; model changes require explicit configuration records |

**Domain 3 is closed.** All decisions PI-01 through PI-50 are finalized.


## 7.2 Remaining architecture domains

Domains 4–8 are consolidated in Section 9. Domain 4 records the decisions made interactively and the final delegated knowledge-ingestion decision. Domains 5–8 record lean implementation defaults selected under the user's instruction to stop extended design discussion and begin development. Product-depth questions are deliberately deferred to Section 10.

# 8. Scope and completeness note

This document consolidates the original architecture baseline and the
decisions/alternatives/diagrams preserved in the current architecture
discussion. It is not a literal, word-for-word export of every chat
message. The Mermaid diagrams are editable representations of the
architecture decisions and discussion diagrams; they are not screenshots
of the chat UI.

Before implementation, the approved design should be translated into
detailed architecture specifications, ADRs, database schemas, API
contracts, workflow definitions, threat models, deployment topology and
phase exit criteria.

**Current checkpoint:** Domains 1–4 finalized. Domains 5–8 have implementation-ready defaults selected under the user's instruction to make the remaining necessary architecture decisions autonomously. These decisions define a starting baseline; they do not imply that implementation is complete.

## 7.2 Domain 4 --- Database and Knowledge Architecture

**Status: In progress. Decision DB-01 through DB-03 finalized.**

### Decision 1 --- Neo4j tenant isolation

**Approved:** Hybrid isolation. Use a shared Neo4j database by default,
with mandatory tenant/project authorization enforced by a dedicated
Graph Access Service. Support dedicated Neo4j databases or deployments
for enterprise organizations requiring stronger infrastructure
isolation.

Implementation rules:

- Tenant-owned graph entities and relationships retain organization
  and project scope where applicable.
- The Graph Access Service derives scope from authenticated identity
  and authorized memberships, not untrusted agent-supplied filters.
- All graph reads and writes pass through the service.
- Tenant and project filters are enforced for queries, traversals and
  search operations.
- Enterprise isolation is provisioned through explicit policy.
- Graph synchronization workers follow the same scope rules.
- Automated tests verify cross-tenant and cross-project access denial.

### Domain 4 decision register

| ID | Finalized decision |
|---|---|
| DB-01 | Shared Neo4j database by default |
| DB-02 | Mandatory tenant/project enforcement through Graph Access Service |
| DB-03 | Dedicated Neo4j database or deployment available for enterprise isolation |

### Decision 2 --- Knowledge ingestion and graph synchronization

**Approved:** Hybrid graph ingestion: asynchronous processing with
validation before snapshot publication. Tasks requiring graph context
wait for a compatible validated snapshot rather than silently using
incomplete graph data.

Implementation rules:

- Changes produce durable events through the transactional outbox or
  equivalent persistent event mechanism.
- Background workers process graph updates asynchronously.
- Graph workers are idempotent and support retry/reconciliation.
- Validation checks source revision and graph processing completeness.
- Only validated snapshots are published for task consumption.
- Tasks pin the graph snapshot they consume.
- If a required snapshot is not ready, the task waits; it must not
  silently consume a partially updated graph.

### Domain 4 decision register

| ID | Finalized decision |
|---|---|
| DB-01 | Shared Neo4j database by default |
| DB-02 | Mandatory tenant/project enforcement through Graph Access Service |
| DB-03 | Dedicated Neo4j database or deployment available for enterprise isolation |
| DB-04 | Asynchronous graph ingestion with durable events and idempotent workers |
| DB-05 | Validate graph updates before publishing snapshots |
| DB-06 | Tasks requiring graph context wait for a compatible validated snapshot |

### Decision 3 --- Repository graph update strategy

**Approved:** Hybrid indexing. Use incremental indexing for normal Git
commits and reserve full repository re-indexing for parser/schema changes,
graph corruption and reconciliation. Preserve commit-level graph snapshots.
Full rebuilds are triggered automatically for detected structural/parser
changes or corruption, and can also be initiated manually by an authorized
administrator when required. Routine full rebuilds are not mandatory.

Implementation rules:

- Normal commits identify changed files and update affected graph entities
  and relationships.
- File additions, modifications, deletions and renames must be handled.
- Full re-indexing is available for parser/schema changes, corruption and
  reconciliation.
- Every published repository graph snapshot records its source commit.
- Tasks pin the exact validated snapshot they consume.
- Re-indexing and incremental updates must preserve tenant/project scope,
  idempotency and validation requirements from Decisions 1 and 2.

### Domain 4 decision register

| ID | Finalized decision |
|---|---|
| DB-01 | Shared Neo4j database by default |
| DB-02 | Mandatory tenant/project enforcement through Graph Access Service |
| DB-03 | Dedicated Neo4j database or deployment available for enterprise isolation |
| DB-04 | Asynchronous graph ingestion with durable events |
| DB-05 | Idempotent workers and validation before snapshot publication |
| DB-06 | Tasks wait for compatible validated graph snapshots |
| DB-07 | Incremental repository indexing for normal commits |
| DB-08 | Full re-indexing for parser/schema changes, corruption and reconciliation |
| DB-09 | Preserve commit-level repository graph snapshots |
| DB-10 | Authorized manual full rebuilds are supported; routine full rebuilds are not required |

### Decision 4 --- Initial repository graph extraction scope

**Approved:** Engineering MVP with polyglot language support.

The initial Repository Knowledge Graph (Repository KG) will extract
repository structure and engineering-level code intelligence, including:

- Repository, branch and commit.
- Directories and files.
- Packages/modules and imports/dependencies.
- Classes, functions and methods.
- API endpoints where detectable.
- Tests and test-to-code relationships.
- Core structural relationships such as CONTAINS, DEFINES, DEPENDS_ON,
  CALLS where reliably extractable, TESTS and MODIFIES.

Language support is designed to be polyglot. The extraction pipeline
should use language-aware parsers/adapters and record which language
and parser/version produced each extraction. Support should be added
through parser adapters rather than hard-wiring the graph schema to one
language.

Deep runtime call-graph analysis, advanced data-flow analysis and
complex cross-language semantic resolution are deferred beyond the
initial implementation.

### Domain 4 decision register

| ID | Finalized decision |
|---|---|
| DB-01 | Shared Neo4j database by default |
| DB-02 | Mandatory tenant/project enforcement through Graph Access Service |
| DB-03 | Dedicated Neo4j database or deployment available for enterprise isolation |
| DB-04 | Asynchronous graph ingestion with durable events |
| DB-05 | Idempotent workers and validation before snapshot publication |
| DB-06 | Tasks wait for compatible validated graph snapshots |
| DB-07 | Incremental repository indexing for normal commits |
| DB-08 | Full re-indexing for parser/schema changes, corruption and reconciliation |
| DB-09 | Preserve commit-level repository graph snapshots |
| DB-10 | Authorized manual full rebuilds are supported; routine full rebuilds are not required |
| DB-11 | Engineering-level repository graph extraction (Engineering MVP) |
| DB-12 | Polyglot language support through language-aware extraction adapters |
| DB-13 | Deep runtime and advanced data-flow analysis deferred beyond MVP |

# 9. Final architecture decisions for development

**Decision status:** Domain 4 is closed. The remaining implementation-level decisions in Domains 5–8 below were selected by the assistant under the user's explicit delegation to make the best necessary architecture decisions, keep the scope lean, and move into development. They are recommended defaults for the first implementation, not claims about existing code or deployed infrastructure.

## 9.1 Domain 4 — Database and Knowledge Architecture (closed)

### Engineering Knowledge Graph population — finalized by delegated decision

**Selected approach: Document-first hybrid ingestion with controlled validation and promotion.**

- Project documents (PRDs, architecture documents, API specifications, decision records, engineering standards and approved issue/task context) are the primary source for Engineering KG candidates.
- Repository analysis supplies supporting evidence and implementation references; source code is not treated as authoritative proof of business intent or architectural approval.
- Users can manually add, correct, reject or supersede extracted knowledge.
- Extracted items enter a candidate/review state. They are not treated as trusted project knowledge until validation succeeds.
- Organization-wide promotion remains a separate explicit approval action. No automatic cross-project publication is permitted.
- Every knowledge item retains source, owner, project scope, extraction/transform version, validation status and revision history. Secrets and sensitive material are excluded from promotion.

This closes Domain 4 while preserving the original specification's separation of Repository KG and Engineering KG, provenance, project-private knowledge and controlled organization-level promotion.

### Consolidated Domain 4 decision register

| ID | Finalized decision |
|---|---|
| DB-01 | Shared Neo4j database by default |
| DB-02 | Mandatory tenant/project enforcement through Graph Access Service |
| DB-03 | Dedicated Neo4j database or deployment available for enterprise isolation |
| DB-04 | Asynchronous graph ingestion using durable events |
| DB-05 | Idempotent workers; validate before publishing graph snapshots |
| DB-06 | Tasks requiring graph context wait for a compatible validated snapshot |
| DB-07 | Incremental repository indexing for normal commits |
| DB-08 | Full re-index for parser/schema changes, corruption and reconciliation |
| DB-09 | Preserve commit-level repository graph snapshots |
| DB-10 | Authorized manual full rebuilds supported; routine full rebuilds not mandatory |
| DB-11 | Engineering-level Repository KG extraction for MVP |
| DB-12 | Polyglot language support through language-aware parser adapters |
| DB-13 | Deep runtime and advanced data-flow analysis deferred |
| DB-14 | Engineering KG is document-first, supplemented by repository evidence and manual curation |
| DB-15 | Extracted knowledge is validated before trusted publication |
| DB-16 | Organization knowledge promotion always requires explicit approval |

### Domain 4 implementation boundary

Build only the graph capabilities needed for the first engineering workflow: tenant-scoped graph access, repository indexing, document-derived Engineering KG candidates, provenance, snapshot publication, retrieval and access tests. Advanced graph analytics, broad ontology design and enterprise-dedicated deployments are not Phase 1 blockers.

## 9.2 Domain 5 — Prompt, Artifact and Execution Contracts

**Selected architecture: one versioned contract and artifact model owned by the Factory control plane.**

1. **Task contract:** Use a versioned JSON Schema as the canonical input/output contract for agent tasks. Validate contracts at creation and before dispatch. Include organization/project/task/execution identifiers, objective, constraints, acceptance criteria and pinned context references.
2. **Execution manifest:** Generate an immutable manifest for every execution attempt. Record task/attempt IDs, provider/runtime/model profile, prompt and tool versions, Git input/output commits, graph snapshots, artifact references, checkpoints, test results, usage/cost where available, status and approvals.
3. **Prompt registry:** Keep published prompt versions immutable. Draft, evaluate, approve, publish, deprecate and revoke through explicit lifecycle states. Every attempt pins prompt version and content/rendered hashes.
4. **Artifacts:** PostgreSQL stores artifact metadata and version references; S3-compatible object storage stores large file content. Use tenant/project-scoped object keys, content hashes, encryption and retention policies.
5. **Context pinning:** A task's PRD, architecture, prompt, Git commit, graph snapshots, API contracts and approved knowledge revisions are pinned. Changes do not silently mutate an active task's context.
6. **No premature schema explosion:** Start with the entities and schemas required for task dispatch, execution manifest, prompt version, artifact metadata and context snapshot. Add specialized artifact types as real workflows require them.

**Domain 5 exit condition:** A task can be created, validated, dispatched and replayed/reconstructed from its immutable contract and manifest references.

## 9.3 Domain 6 — Quality, Verification and Delivery

**Selected architecture: deterministic quality gates plus independent review and explicit human-controlled delivery.**

- Every task declares acceptance criteria and required verification checks before execution.
- Initial pipeline: formatting/lint and static checks → unit tests → relevant integration/build checks → security scan → independent code review → acceptance-criteria verification.
- The implementing agent cannot approve its own changes. QA and review are separate responsibilities, even if they initially run on shared worker infrastructure.
- The Integration Coordinator owns branch/worktree integration, conflict detection, rebase/merge preparation and pull-request creation.
- Agents never write directly to protected `main` or equivalent branches.
- A pull request may be prepared automatically after required checks pass; merge, protected-branch modification and production deployment remain human-authorized actions.
- Store verification evidence and reviewer decisions against the execution/task and include references in the manifest.
- Failed gates return actionable findings to the task workflow; retries create traceable attempts rather than overwriting prior results.

**MVP quality gate:** build succeeds, relevant tests pass, no unresolved critical security finding, acceptance criteria are checked, and independent review is recorded. Exact thresholds and tool choices are configured per project later.

**Domain 6 exit condition:** The factory produces a reviewable pull request with reproducible test/review evidence and an approval trail.

## 9.4 Domain 7 — Security, Governance and Audit

**Selected architecture: centralized policy decisions with enforcement at every resource boundary.**

- Authentication and authorization are enforced in FastAPI services; organization/project roles and resource grants are checked server-side.
- PostgreSQL RLS is defense in depth, not a replacement for service authorization. Neo4j access is mediated by Graph Access Service. Object storage access uses scoped, short-lived access paths or credentials.
- Provider secrets are stored in an external secrets manager. PostgreSQL stores metadata and references only. A Credential Broker injects narrowly scoped credentials into authorized executions; raw secrets must not enter prompts, logs, manifests or artifacts.
- Docker execution is non-privileged, resource-limited, isolated per attempt, and has restricted network and filesystem access. No unrestricted host mounts or ambient host credentials.
- Repository files, issues and documents are untrusted inputs. Apply prompt-injection-aware handling, tool allowlists, least privilege, output validation and sensitive-data redaction.
- Audit security-sensitive events: membership/role changes, credential use, policy changes, graph access/promotion, prompt publication, approvals, protected Git operations and administrative rebuilds.
- Human approval is mandatory for production deployment, protected-branch changes, destructive database operations, credential/permission changes, organization knowledge promotion, prompt publication and sensitive external actions.
- Define retention, deletion, export and provider data-handling policies before onboarding external customers; do not block local development on a full compliance program.

**Domain 7 exit condition:** Cross-tenant/project isolation tests pass, secrets are not persisted in application records/logs, sensitive actions require authorization, and security-relevant actions are auditable.

## 9.5 Domain 8 — Infrastructure and Production Readiness

**Selected architecture: modular control plane with independently scalable worker processes; avoid premature microservices.**

- Keep the initial FastAPI control plane and domain modules in a modular application. Separate deployable workers/processes are used where isolation or workload characteristics require them: Temporal workers, provider/runtime workers, graph-ingestion workers and quality workers.
- Use Temporal for durable workflow lifecycle. Redis is cache/transport/coordination, never the only durable record of work. PostgreSQL and the transactional outbox remain recoverable sources for canonical state and events.
- Local development should use a reproducible Docker Compose environment for PostgreSQL, Redis, Neo4j, Temporal and the application dependencies. External object storage can be represented by an S3-compatible local service in development.
- Keep environment configuration and secrets outside source control. Provide `.env.example` with names/placeholders only; never commit credentials.
- CI must run formatting, linting, type/static checks, unit tests, integration tests for persistence/authorization and build checks. Add container and dependency scanning before production exposure.
- Add health/readiness checks, structured logs, correlation IDs, OpenTelemetry traces/metrics and Langfuse integration for model interactions.
- Back up PostgreSQL and object storage with tested restore procedures. Neo4j is rebuildable, but its snapshot metadata and ingestion source records must be backed up. Define recovery objectives before production launch.
- Scale execution and graph workers horizontally based on queue depth, concurrency limits, provider quotas and resource availability. Apply per-organization/project quotas and fair scheduling.
- Do not set production SLOs, Kubernetes requirements, multi-region topology or dedicated tenant infrastructure until workload, customer and deployment requirements justify them.

**Domain 8 exit condition:** A clean environment can be brought up repeatably, CI passes, workers can be restarted without losing durable workflow state, and backup/restore has been exercised before production use.


## 9.6 Repository Intelligence workspace and graph experience

**Decision: Repository Intelligence is a dedicated project-level workspace.**
It is distinct from the general Knowledge Graph Explorer and is the primary
human-facing and agent-facing entry point for understanding a project's
source-code structure.

### Product placement

Within each project workspace, provide a dedicated **Repository Intelligence**
area with the following initial views:

- **Repository Graph:** interactive graph of files, symbols, APIs, tests,
  packages and dependencies.
- **Code Intelligence:** search and navigate files, symbols, dependencies
  and references.
- **Indexing & Sync:** indexing jobs, source commit, parser version, freshness,
  validation status and failures.
- **Graph History:** published commit-level graph snapshots and changes
  between snapshots.

The global Knowledge Graph Explorer remains the broader exploration surface
for authorized Repository KG and Engineering KG information. Project-level
Repository Intelligence is the focused repository view.

### Data and service architecture

```text
Git Repository
      |
      v
Repository Indexing Pipeline
      |
      +-- Language-aware parser adapters
      +-- Optional Graphify extraction adapter
      |
      v
Graph Normalization and Validation
      |
      v
Repository KG in Neo4j
      |
      +-----------------------------+
      |                             |
      v                             v
Graph Access Service          Repository Intelligence UI
      |                             |
      v                             v
Authorized Agent Retrieval     Human Graph Exploration
```

- Neo4j stores persistent graph entities and relationships; the UI does
  not treat a screenshot or generated graph file as the canonical graph.
- Graphify may be evaluated and integrated as an extraction/indexing adapter
  if its output can be normalized into the approved Repository KG schema.
  It is not the graph database, source of truth, or a mandatory runtime
  dependency.
- The normalized Repository KG remains provider- and extractor-independent.
- The Graph Access Service is the only supported application interface for
  graph reads and writes. Users and coding agents do not connect directly
  to Neo4j.
- Human graph exploration and agent context retrieval use the same
  authorization boundaries, but can expose different purpose-specific
  query operations.
- Agent retrieval returns bounded, relevant context (for example, related
  symbols, dependency paths, tests and source locations), not the entire
  repository graph in every prompt.
- Every retrieval records the project scope and graph snapshot used, so the
  execution manifest can preserve reproducibility.

### Snapshot and freshness behavior

- Published repository graph snapshots are tied to exact Git commits and
  indexing/parser versions.
- Users can inspect the latest published snapshot and its source commit.
- Agents pin a compatible validated snapshot in their execution contract.
- If a required snapshot is unavailable, the task follows the approved
  wait policy rather than consuming a partially updated graph.
- Indexing failures, stale status and rebuild operations are visible in the
  Indexing & Sync view.
- Graph history exposes snapshot metadata and change summaries; full graph
  diff visualization can be implemented after the initial graph experience.

### MVP scope

For the first Repository Intelligence release, implement:

1. Repository graph visualization for the approved Engineering MVP entities.
2. Search and inspect file/class/function/method nodes.
3. Navigate `CONTAINS`, `DEFINES`, `DEPENDS_ON`, `CALLS` where reliable,
   `TESTS` and `MODIFIES` relationships.
4. Show selected entity details and source file/path/line references where
   available.
5. Show source commit, parser/indexer version, snapshot status and last
   successful indexing time.
6. Provide authorized graph retrieval APIs for coding agents.
7. Enforce organization/project authorization through the Graph Access
   Service for every UI and agent query.

Defer advanced graph layout controls, runtime call graphs, deep data-flow
analysis, complex cross-language resolution and sophisticated graph-diff
visualization until real usage justifies them.

### Navigation model

| Navigation location | Responsibility |
|---|---|
| Project → Repository Intelligence | Focused repository graph and code intelligence |
| Project → Knowledge | Engineering KG, requirements, decisions and approved knowledge |
| Global → Knowledge Graph Explorer | Broader exploration across authorized graph domains |
| Workflow → Execution Context | Show the exact graph snapshot consumed by an execution |

This refines the existing Repository KG and Engineering KG architecture; it
does not introduce a third graph database or replace either graph domain.

# 10. Product decisions to discuss later — explicitly not development blockers

The following questions belong to deeper product discovery and should be revisited when a working end-to-end MVP exists or when a concrete customer/use case requires them. Do not expand the architecture or delay Phase 0/1 to answer all of them now.

## 10.1 Product experience and workflow

- Which user journeys are primary: issue-to-PR, PRD-to-implementation, bug-fix, feature delivery, repository Q&A or all of these?
- What is the first-class project lifecycle and how are projects created, archived, cloned and handed over?
- How much autonomy can users grant to each agent/workflow, and which actions require confirmation?
- How should users intervene, pause, resume, cancel, reprioritize or re-plan running work?
- What should the approval center, workflow visualizer and agent command center show at MVP versus later?
- How are templates, reusable workflows and organization-level engineering standards configured?

## 10.2 Agent workforce and orchestration depth

- Which agent roles are mandatory for the first usable workflow, and which can be capabilities of a smaller number of agents initially?
- What are the exact role-specific input/output schemas, tool permissions and evaluation datasets?
- How should dynamic task expansion, replanning and task cancellation behave under partial completion?
- What are the limits for parallel agents, nested delegation and per-project concurrency?
- Which human-in-the-loop checkpoints are configurable by organization/project?

## 10.3 Provider and runtime support

- Which concrete providers/runtimes are supported first, based on available credentials, licensing and tested adapters?
- Which runtime capabilities are mandatory for coding agents: terminal, filesystem, Git, browser, session recovery, streaming and structured outputs?
- How are provider-specific data retention, residency, rate limits and terms represented in organization policy?
- What are the budget controls, cost alerts and fallback thresholds?
- Which local model/runtime configurations need GPU scheduling or on-prem deployment?

## 10.4 Repository intelligence and knowledge product

- Which language parsers and frameworks are prioritized based on actual target repositories?
- How are monorepos, generated code, vendored dependencies, submodules and very large repositories handled?
- What graph query experiences are exposed to agents and humans, and what is the freshness expectation for each?
- What document types, extraction confidence thresholds, review UX and knowledge lifecycle states are required?
- How are conflicting, superseded, stale or disputed engineering decisions represented?
- What search mix is needed across graph traversal, keyword search and vector retrieval?
- What are the retention and deletion semantics for project knowledge and promoted organization knowledge?

## 10.5 Quality, security and governance depth

- Which language-specific linters, test frameworks, SAST/dependency scanners and policy engines are supported per project?
- What acceptance criteria are machine-verifiable, and how are subjective criteria reviewed?
- What are the exact approval policies for production, infrastructure, database migrations and external actions?
- What threat model, tenant assurance, compliance controls and audit retention are needed for target customers?
- What data can be sent to each provider, and what redaction or private deployment modes are required?

## 10.6 Commercial and operational product decisions

- Is the product initially single-organization self-hosted, hosted multi-tenant SaaS, or both?
- What are the plans, billing units, quotas, seat model and cost attribution rules?
- What are target latency, throughput, availability, recovery-time and recovery-point objectives?
- What tenant scale, repository size, execution volume and retention period should drive capacity planning?
- Which integrations beyond GitHub are needed (GitLab, Bitbucket, Jira, Linear, Slack, identity providers and cloud platforms)?

# 11. Development start recommendation

**Start development now.** The architecture has enough definition to implement the foundation without waiting for the deferred product decisions.

## 11.1 First implementation slice

Build a thin, end-to-end vertical slice before implementing the entire platform:

1. Repository scaffold, local development environment and CI.
2. FastAPI application with organization/project identity and authorization boundaries.
3. PostgreSQL migrations for organizations, users/memberships, projects, repositories, tasks, task attempts, executions and audit events.
4. Angular application shell with authentication, organization/project selection and a basic project workspace.
5. GitHub repository connection and repository metadata capture.
6. One canonical task contract and execution manifest schema.
7. Temporal workflow that creates and tracks one task execution.
8. One provider adapter/runtime path and one isolated Docker/Git worktree execution.
9. Persist logs/status/results and produce a basic execution report.
10. A minimal test/build verification step and human-reviewed pull request path.

Do not begin by building every agent, every provider adapter, the complete graph ontology or every dashboard.

## 11.2 Phase gates and order

Follow the source specification's phase-gated roadmap:

- **Phase 0 — Architecture and Engineering Foundation:** repository structure, module boundaries, API conventions, migrations strategy, security baseline, local environment, CI and ADRs.
- **Phase 1 — Multi-Tenant Factory Foundation:** organization/project access, Angular shell, FastAPI, PostgreSQL, GitHub integration, basic tasks, prompt registry, artifact references and manifest.
- **Phase 2 — Agent Orchestration and Recovery:** Temporal, LangGraph, one working provider/runtime adapter, execution contract, checkpoints and recoverable attempts.
- **Phase 3 — Parallel Engineering:** DAGs, scheduler, isolated worktrees, integration coordinator and multi-user concurrency.
- **Phase 4 — Repository and Engineering Intelligence:** Neo4j, Repository KG, Engineering KG, graph sync, snapshots and controlled knowledge sharing.
- **Phase 5 — Quality, Verification and Governance:** independent QA/review, security checks, approval workflows, audit, cost and observability dashboards.
- **Phase 6 — Production Readiness:** quotas, multi-project scale, disaster recovery, deployment automation and enterprise controls.

A phase is complete only when its exit criteria and acceptance tests pass. Do not reopen a completed phase for cosmetic enhancements; create a separately scoped follow-up only when a material defect or requirement warrants it.

## 11.3 First successful factory demonstration

Retain the source specification's target demonstration: two users on one project using different providers, isolated worktrees, versioned contracts/manifests, graph updates, provider interruption and handover, integration, QA/review, pull request and human approval. Implement this progressively; do not make the complete demonstration a prerequisite for the first vertical slice.

# 12. Final status and handoff

- Domains 1–3: finalized through the prior decision discussions.
- Domain 4: finalized, including delegated Engineering KG ingestion defaults and the Repository Intelligence workspace/agent graph access design.
- Domains 5–8: implementation-ready defaults selected under the user's delegation.
- Product-depth questions: captured in Section 10 for later discovery.
- Development: authorized to begin with Phase 0 and the first vertical slice in Section 11.

The original `Software Factory.txt` remains the architectural baseline. This decision log refines it for implementation; it does not replace the product vision, core principles, nine logical layers, original phase gates or first-successful-factory objective.

