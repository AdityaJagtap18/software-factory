# Repository & Engineering Knowledge Graph Audit

Scope: Neo4j-backed knowledge graph infrastructure, Repository Knowledge Graph
(code structure), Engineering Knowledge Graph, repo indexing lifecycle,
agent use of the graph, and graph security/multi-tenancy. RAG/vector search
and document indexing are explicitly out of scope and are a different
subsystem — see boundary note in 3.1.

Method: read `docs/implementation/*.md` and
`Software_Factory_Architecture_Decision_Log (1).md` (Domain 4, section 9.1,
9.6) for the intended architecture; then read every backend file that
references `neo4j`; then started the project's own `softwarefactory-neo4j-1`
Docker container (it was stopped, matching `backend/.env`/`config.py`
`neo4j_uri=bolt://localhost:7688`) and ran read-only Cypher via
`cypher-shell` to inspect actual node/relationship counts, constraints and
indexes. The container was stopped again afterward to restore its prior
state. No application source files were modified.

---

## 3.1 Knowledge Graph Infrastructure

**Is Neo4j actually integrated?** Yes, but only a thin, single-file slice.

- Driver/config: `backend/app/core/config.py` lines 16-18 define
  `neo4j_uri` (`bolt://localhost:7688`), `neo4j_user`, `neo4j_password`.
  `backend/app/services/knowledge_graph.py` lines 25-30 build a cached
  `neo4j.GraphDatabase.driver(...)` singleton (`@lru_cache` on `_driver()`).
  The real `neo4j` Python driver is installed in `backend/.venv`.
- DB initialization: **none**. No module creates constraints or indexes.
  `grep` for `CREATE CONSTRAINT`/`CREATE INDEX` across `backend/app/` returns
  zero matches. A live query against the project's own Neo4j container
  (`SHOW CONSTRAINTS` → empty; `SHOW INDEXES` → only the two default
  Neo4j-5 token-lookup indexes that exist in any fresh database) confirms
  there is no application-defined schema, constraint, or index at all.
- Graph schema / node labels actually implemented, read straight from code
  in `knowledge_graph.py`: `Project`, `User`, `Connection` (coding-agent
  connection), `Workflow`, `Task`, `File`, `Class`, `Function`. That is the
  complete label set in the codebase.
- Relationship types actually implemented: `HAS_WORKFLOW`, `HAS_TASK`,
  `CREATED`, `ASSIGNED_TO`, `HAS_STEP {order}`, `HAS_FILE`, `DEFINES`.
  These mirror Postgres entities (tasks/workflows/connections/users) plus a
  very small code-structure slice (file → class/function). None of the
  documented engineering-level relationships (`CONTAINS`, `DEPENDS_ON`,
  `CALLS`, `TESTS`, `MODIFIES`) exist anywhere in the backend.
- Tenant/project isolation: every node/query carries a `project_id`
  property or is matched through a `Project` node by `id`, but this is
  isolation-by-convention inside `knowledge_graph.py` itself, not a
  separate enforced layer (see 3.5).
- Graph query services / Cypher generation: all Cypher is hand-written and
  inline in `knowledge_graph.py` (`sync_project`, `ingest_repository`,
  `get_code_graph`, `get_project_graph`). One query
  (`ingest_repository`, line ~283) builds the Cypher label dynamically via
  an f-string (`MERGE (s:{label} ...)`), which is safe here because `label`
  is restricted to a 2-value internal constant, not user input, but it is
  still a code smell for an otherwise parameterized module.
- Ingestion pipeline: `ingest_repository()` calls
  `code_ingestion.scan_directory()` (see 3.2) and MERGEs the resulting
  files/symbols; it DETACH DELETEs the project's previous `File`/symbol
  subgraph first, so each run fully replaces that slice (no incremental
  diffing).
- Update mechanism: `sync_project()` re-reads Postgres tasks/workflows and
  MERGEs the same nodes idempotently; there is no scheduler, webhook, or
  background worker — both `sync_project` and `ingest_repository` are only
  invoked synchronously from the two API routes in
  `backend/app/api/routes/knowledge.py`.
- Visualization: `GET /projects/{id}/knowledge/graph` and
  `GET /projects/{id}/knowledge/code-graph` return nodes/edges as JSON;
  no frontend graph-rendering code was in scope for this backend audit
  (frontend is a separate agent's scope per the task framing, but
  `docs/implementation/DECISIONS_AND_GAPS.md` line 25 already states "No
  Neo4j/graph backend — Knowledge Graph Explorer and Repository
  Intelligence pages render with mock graph data for layout purposes
  only" — i.e., even where a UI exists, it was built against mock data,
  not this real endpoint).
- Persistence: verified live. Starting the project's own
  `softwarefactory-neo4j-1` container and running `MATCH (n) RETURN
  count(n)` returned **0** — the graph is currently completely empty.
  Nothing in this environment has ever durably ingested data into it
  (or a prior ingestion was wiped by a volume/container reset). This
  matches the code: nothing in the backend calls `sync_project` or
  `ingest_repository` automatically; they only run on-demand from the UI.

**Boundary note (per task instructions):** this is a separate concern from
RAG/vector search. No vector-embedding or similarity-search code was found
near `knowledge_graph.py`; embeddings are out of scope here and were not
further audited.

**Status: PARTIALLY IMPLEMENTED.** A real, working Neo4j connection and a
small, genuinely-functional (not mocked) sync/ingest/read code path exist.
But there is no schema definition (constraints/indexes), no background
ingestion, and the live database is empty.

---

## 3.2 Repository Knowledge Graph

Can the platform build a graph from connected Git repos? **No, not from a
connected Git repo** — only from a local directory path on the backend
host.

- `backend/app/services/code_ingestion.py`: `scan_directory(root: Path)`
  walks a local filesystem path (capped at 2,000 files), parses:
  - Python via the real `ast` module → real `FunctionDef`/`AsyncFunctionDef`
    /`ClassDef` nodes with real line numbers (`_parse_python`).
  - TypeScript/JavaScript via a single regex (`_TS_SYMBOL_RE`) matching
    `export class/function`, `export const`, or bare `class`/`function` —
    a lightweight pattern matcher, not an AST/compiler-based parser; it can
    miss or misattribute non-trivial syntax, by its own code comment.
  - No other language adapters exist (no Go, Java, Rust, C#, etc.).
- The entry point (`knowledge_graph.ingest_repository`) takes an explicit
  `root_path` string from the HTTP request body
  (`backend/app/schemas/knowledge.py` `IngestRepositoryRequest`) — it is
  **not** wired to the platform's actual Git integration
  (`backend/app/services/git_sync.py`, `git_provider/`,
  `git_webhook.py`). There is no code path that clones/reads a connected
  GitHub/GitLab repository and ingests it into the graph. The code comment
  in `knowledge_graph.py` (lines 1-5, 230) is explicit about this: "This
  never fetches a remote git URL... `root_path` must be a directory the
  backend process can already see."
- Of the documented extraction targets (repositories, branches, commits,
  directories, files, classes, functions, methods, symbols, imports,
  dependencies, API endpoints, DB models, DB relationships, config
  dependencies, tests, docs, inter-module relationships), the ONLY ones
  actually extracted and stored are: **files** (path + language) and
  **top-level classes/functions** (name + line). Nothing else — no
  branches, no commits, no imports/dependencies, no API endpoints, no DB
  models, no tests, no docs, no inter-module relationships.
- Relationships like "Function A calls Function B", "Module A imports
  Module B", "API endpoint invokes Service", "Service accesses DB Model",
  "Test validates Function" are **not stored, and not even transiently
  computed** — there is no call-graph, import-graph, or test-mapping logic
  anywhere in `code_ingestion.py` or `knowledge_graph.py`. The only
  relationship the ingestion path creates is `(File)-[:DEFINES]->
  (Class|Function)`.

**Status: PARTIALLY IMPLEMENTED (file/top-level-symbol extraction only),
NOT IMPLEMENTED for every relationship type beyond "file defines symbol",
and NOT IMPLEMENTED for building from a connected Git repository** — it
only reads a local path, disconnected from the platform's own Git
integration.

---

## 3.3 Repository Indexing Lifecycle

| Step | Status | Evidence |
|---|---|---|
| Repo connection → indexing trigger | NOT IMPLEMENTED | `RepositoryConnection` (git_integration models) and `knowledge_graph.ingest_repository` are entirely separate code paths; connecting a repo does not trigger ingestion. |
| Initial ingestion | PARTIALLY IMPLEMENTED | Manual-only, via `POST /projects/{id}/knowledge/ingest-repository` with an arbitrary local path; project-admin-gated. |
| File discovery | IMPLEMENTED AND VERIFIED | `code_ingestion.scan_directory` — real filesystem walk, verified by reading the code; skip-dirs and 2,000-file cap are real and enforced. |
| Parsing / symbol extraction | PARTIALLY IMPLEMENTED | Real `ast`-based Python parsing; regex-based, not AST-based, TS/JS parsing; no other languages. |
| Dependency extraction (imports, API endpoints, DB models, etc.) | NOT IMPLEMENTED | No code anywhere extracts imports, dependencies, endpoints, or DB models into the graph. |
| Embedding generation | NOT IMPLEMENTED (and out of this audit's scope per task framing) | No embedding calls found near this code; this is the RAG agent's domain, not graph. |
| Graph persistence | IMPLEMENTED AND VERIFIED | `MERGE` writes confirmed by reading `knowledge_graph.py`; live DB currently empty but the write path is genuine, parameterized Cypher, not mocked. |
| Incremental updates after commits | NOT IMPLEMENTED | No git-commit webhook or worker calls `ingest_repository`; `git_webhook.py` only updates PR state (`task.git_pr_state`), never touches the graph. |
| Full re-indexing after parser/schema change | PARTIALLY IMPLEMENTED | `ingest_repository` always does a full DETACH DELETE + re-MERGE of the project's File/symbol subgraph on every call — so "full re-index" exists as the *only* mode; there is no separate incremental-vs-full distinction, no parser-version tracking, and no automatic trigger for it. |
| Deleted/renamed file handling | PARTIALLY IMPLEMENTED | Handled only as a side effect of full replacement (old File/symbol nodes are deleted every run); there is no rename-detection or diff-based handling. |
| Graph snapshot management | NOT IMPLEMENTED | No snapshot/versioning concept exists. No node carries a source commit SHA, a parser version, or a snapshot ID. This directly contradicts architecture decisions DB-09 ("preserve commit-level repository graph snapshots") and DB-05/DB-06 (validated snapshots that tasks pin). |

---

## 3.4 Graph-Powered Coding Agents

**Do coding agents query the repository knowledge graph? No evidence found
— plainly: this platform does NOT have graph-powered coding intelligence
today.**

- `backend/app/services/task_execution.py` (the only place a task is
  actually run) was read in full. It: loads the `CodingAgentConnection`,
  runs a health check, optionally prepares a Git worktree
  (`git_worktree.prepare_worktree`), and calls
  `adapter.start_execution_streaming(task.description or task.title,
  credential_value, on_chunk, should_cancel, cwd=worktree.path if worktree
  else None)`. There is **no import of `knowledge_graph`, no Cypher call,
  no graph-retrieval tool** anywhere in this file.
- `backend/app/services/agent_runtime/base.py`, `adapters.py`,
  `registry.py` define the `CodingAgentRuntimeAdapter` interface
  (`health_check`, `start_execution_streaming`) — there is no tool/context
  object passed to an adapter that could carry graph context, and no
  adapter implementation references `neo4j` or `knowledge_graph` (`grep`
  for `knowledge_graph|neo4j|graph` across `agent_runtime/*.py`,
  `task_execution.py`, `git_sync.py`, `git_worktree.py` returned zero
  matches).
- What an agent actually gets: a bare text prompt (`task.description` or
  `task.title`) plus, if a repo is connected, a real Git worktree checkout
  on disk (`cwd=worktree.path`) that the underlying CLI tool (Claude Code,
  Codex, etc.) can inspect with its own file-reading tools. This is **raw
  file/filesystem inspection by the external CLI tool itself**, not graph
  retrieval and not vector/RAG retrieval initiated by this platform.

**Status: NOT IMPLEMENTED.** Retrieval during agent execution is "give the
agent a working-tree checkout and a prompt," full stop. No hybrid, no
graph-powered reasoning. Any claim of "graph-powered coding agents" in
marketing/product material is not supported by the code.

---

## 3.5 Graph Security and Multi-Tenancy

Documented decision (Decision 1, Domain 4, Architecture Decision Log lines
1421-1448): "shared Neo4j database by default, with mandatory
tenant/project authorization enforced by a dedicated Graph Access Service
... All graph reads and writes pass through the service."

**Does this exist in code? No.**

- There is no `graph_access`, `GraphAccessService`, or any similarly-named
  module anywhere in `backend/app/` (`grep -rniI "graph_access\|GraphAccessService"`
  returns nothing outside this audit's own search).
- All four knowledge routes in `backend/app/api/routes/knowledge.py` use
  the ordinary HTTP-layer dependency `Depends(require_project_access)`
  (from `app/api/deps.py`), i.e. the same Postgres-backed
  organization/project membership check used by every other route in the
  app. That is real API-layer authorization (good), but it is **not** a
  graph-specific access-control layer, and it only gates the four HTTP
  endpoints — it does not and cannot stop a future direct Cypher caller
  elsewhere in the codebase from reading/writing unscoped.
- Inside `knowledge_graph.py` itself, isolation is implemented only as a
  convention: every Cypher query takes a `project_id` parameter and
  matches/merges on it. There is no code that rejects a query lacking a
  project filter, no cross-tenant test, and no enforcement that a caller's
  authenticated identity (vs. an arbitrary `project_id` argument) decides
  scope — the service functions take `project_id`/`Project` objects
  directly from their caller rather than deriving scope from the
  authenticated session themselves, which is the opposite of the
  documented rule ("The Graph Access Service derives scope from
  authenticated identity ... not untrusted agent-supplied filters").
  In practice today this is safe only because the one caller
  (`app/api/routes/knowledge.py`) always passes `ctx.project` from the
  already-checked `ProjectContext` — but that safety lives in the caller,
  not in a graph-access boundary, so any new caller added later could
  bypass it by construction.
- No dedicated/enterprise-isolated Neo4j deployment option (DB-03) exists;
  there is exactly one Neo4j connection configured for the whole app
  (single URI/user/password in `config.py`).
- No automated cross-tenant/cross-project graph-access-denial tests exist
  (`backend/tests/test_knowledge.py` was read in full — it only covers a
  single-org happy-path sync/read round trip gated by `@requires_neo4j`;
  no second-tenant isolation test).

**Status: NOT IMPLEMENTED** for the Graph Access Service described in the
decision log. Isolation that exists today is **BACKEND ONLY, at the
Postgres/API layer** (via `require_project_access`) plus an unenforced
convention inside the one existing graph service module — not the
mandatory, dedicated Graph Access Service the architecture calls for.

---

## Status summary

| Capability | Status |
|---|---|
| Neo4j connection/config | IMPLEMENTED AND VERIFIED |
| Graph schema (constraints/indexes) | NOT IMPLEMENTED |
| Node labels (Project/User/Connection/Workflow/Task/File/Class/Function) | IMPLEMENTED AND VERIFIED (in code; live DB currently empty) |
| Relationship types beyond platform-entity mirroring (CALLS/DEPENDS_ON/TESTS/MODIFIES) | NOT IMPLEMENTED |
| Repository-from-local-path ingestion (files + top-level symbols) | IMPLEMENTED AND VERIFIED |
| Repository-from-connected-Git-repo ingestion | NOT IMPLEMENTED |
| Import/dependency/API-endpoint/DB-model/test extraction | NOT IMPLEMENTED |
| Incremental indexing on commit | NOT IMPLEMENTED |
| Graph snapshotting / commit-pinning | NOT IMPLEMENTED |
| Graph visualization API (data) | IMPLEMENTED AND VERIFIED |
| Graph visualization UI (frontend) | MOCKED-HARDCODED (per `docs/implementation/DECISIONS_AND_GAPS.md`) |
| Graph-powered agent retrieval during task execution | NOT IMPLEMENTED |
| Dedicated Graph Access Service (tenant/project enforcement) | NOT IMPLEMENTED |
| Project-layer isolation on existing graph endpoints | IMPLEMENTED BUT NOT VERIFIED (relies on caller discipline, no cross-tenant test) |
| Engineering KG (document-first ingestion, candidate/review, promotion) | NOT IMPLEMENTED (no code found for any of DB-14/15/16) |

---

## 3.6 Repository Knowledge Graph Deliverable

### Existing graph architecture

A single Neo4j database (`bolt://localhost:7688` in dev, via Docker
Compose) is reached through one Python module,
`backend/app/services/knowledge_graph.py`, using a process-wide cached
driver. Four FastAPI routes
(`backend/app/api/routes/knowledge.py`) expose it: sync platform entities,
read the project graph, ingest a local directory, read the code graph.
Authorization is the ordinary project-membership dependency, not a
dedicated graph service.

### Actual current schema

Nodes: `Project`, `User`, `Connection`, `Workflow`, `Task`, `File`,
`Class`, `Function`.
Relationships: `HAS_WORKFLOW`, `HAS_TASK`, `CREATED`, `ASSIGNED_TO`,
`HAS_STEP {order}`, `HAS_FILE`, `DEFINES`.
No constraints, no indexes beyond Neo4j's own default token-lookup
indexes (verified live via `SHOW CONSTRAINTS`/`SHOW INDEXES` against the
project's own container).

### Current ingestion pipeline

`POST /projects/{id}/knowledge/ingest-repository` → admin-only → takes a
backend-host filesystem path → `code_ingestion.scan_directory` (ast for
Python, regex for TS/JS, 2,000-file cap) → full delete-and-replace of the
project's `File`/symbol subgraph in Neo4j. No trigger from the platform's
own Git integration, no incremental mode, no commit/snapshot metadata, no
parser-version tracking, no scheduling/background worker.

### Existing APIs/services

- `POST /projects/{id}/knowledge/sync` — platform-entity graph sync.
- `GET /projects/{id}/knowledge/graph` — bounded project neighborhood read.
- `POST /projects/{id}/knowledge/ingest-repository` — local-path code
  ingestion (admin only).
- `GET /projects/{id}/knowledge/code-graph` — read back File/Class/Function
  subgraph.

### Missing functionality (relative to the agreed architecture)

1. Graph Access Service (DB-02) — does not exist; isolation is API-layer
   only plus an unenforced convention.
2. Commit-level snapshots, snapshot validation/publication, and
   snapshot-pinning for tasks (DB-04 through DB-10) — none implemented.
3. Connection between Git integration (`git_sync.py`, `RepositoryConnection`,
   webhooks) and graph ingestion — currently zero overlap.
4. Incremental indexing on commit, full re-index triggers on parser/schema
   change, corruption detection/reconciliation (DB-07/DB-08) — none
   implemented; only a single always-full-replace path exists.
5. Engineering-MVP extraction breadth (DB-11): imports/dependencies, API
   endpoints, tests, test-to-code relationships, `CONTAINS`, `DEPENDS_ON`,
   `CALLS`, `TESTS`, `MODIFIES` relationships — all missing; only
   `File-DEFINES->Class/Function` exists.
6. Polyglot parser-adapter framework (DB-12) — only Python (ast) and a
   single regex for TS/JS; no adapter abstraction exists to add languages.
7. Engineering Knowledge Graph (document-first ingestion, candidate/review
   state, provenance, organization promotion — DB-14/15/16) — no code at
   all; this is entirely unbuilt.
8. Agent-facing graph retrieval API/tool (decision log §9.6, item 6) — does
   not exist; agents receive only a prompt and, optionally, a worktree
   checkout.
9. Graph schema (constraints/indexes) — none defined anywhere.

### Proposed implementation sequence (respecting the already-agreed architecture; no redesign — this follows Domain 4 and §9.6 as written)

1. **Schema foundation first.** Add constraint/index creation (idempotent,
   run at startup or via migration) for the already-used labels
   (`Project.id`, `File.{project_id,path}`, etc.) plus the still-missing
   Engineering-MVP labels (`Repository`, `Branch`, `Commit`, `Directory`,
   `Module`, `Package`, `Endpoint`, `Test`) before adding more ingestion
   logic on an unconstrained graph.
2. **Graph Access Service.** Extract a single module that every graph
   read/write (including the existing `sync_project`/`ingest_repository`/
   `get_project_graph`/`get_code_graph` calls) must go through, deriving
   project/org scope from the authenticated `ProjectContext` rather than
   accepting a bare `project_id`/`Project` argument from arbitrary callers.
   Add cross-tenant denial tests. This directly closes the DB-02 gap and
   should land before any new ingestion surface increases what's at risk.
3. **Wire ingestion to the real Git integration.** Replace/extend the
   local-path-only `ingest_repository` with a path driven by
   `RepositoryConnection`/`git_worktree` — ingest the already-checked-out
   worktree instead of (or in addition to) an admin-supplied arbitrary
   path, and record the source commit SHA on the resulting subgraph (the
   minimum needed for DB-09's "preserve commit-level snapshots").
4. **Incremental updates + snapshot/validation model.** Add the durable
   event/outbox-driven worker described in DB-04/DB-05/DB-06: on a new
   commit, diff changed/added/deleted/renamed files, update only the
   affected subgraph, validate, and publish a snapshot record that tasks
   can pin. Keep full re-ingestion as the existing fallback for
   parser/schema changes or detected corruption (DB-07/DB-08).
5. **Extraction breadth (parser-adapter framework).** Introduce the
   language-aware adapter abstraction DB-12 calls for, and use it to add
   the still-missing relationship types in priority order: imports/
   dependencies (`DEPENDS_ON`), test-to-code (`TESTS`), then
   endpoint/service/DB-model relationships — deferring call-graph (`CALLS`)
   and deep data-flow analysis as DB-13 already permits.
6. **Agent-facing retrieval.** Only after 2–5 give the graph real,
   validated, snapshot-pinned content, add a bounded graph-retrieval
   tool/function the agent runtime can call (through the Graph Access
   Service, scoped and snapshot-pinned, per §9.6) — building this earlier
   would just hand agents access to an empty or unvalidated graph.
7. **Engineering KG.** Build last, as its own, document-first pipeline
   (DB-14/15/16), since it is architecturally and functionally independent
   of the Repository KG work above and the decision log treats it as a
   separate domain.

Dependencies: step 3 depends on the Git integration
(`git_sync.py`/`RepositoryConnection`) already being reliable for the
target repos; step 6 depends on agent orchestration
(`task_execution.py`/`agent_runtime/`) exposing a tool-call mechanism to
the underlying CLI adapters, which does not currently exist either and
would need its own design.
