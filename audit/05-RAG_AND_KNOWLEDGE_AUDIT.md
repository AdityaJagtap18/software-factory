# RAG & Document-Knowledge Audit

Scope note: this audit covers **document/vector-based knowledge (RAG)** only.
The Neo4j Engineering/Repository Knowledge Graph is covered by a separate audit.
Where a UI surface is labeled "Knowledge" but is actually graph-backed, that is
called out below and left to the other audit for depth.

## Summary finding

**There is no RAG or document-knowledge system in this codebase.** No document
ingestion, chunking, embedding generation, vector storage, semantic search,
hybrid retrieval, or reranking code exists anywhere in `backend/app/`. The only
backend "knowledge" feature is the Neo4j-backed code/engineering knowledge
graph (`backend/app/services/knowledge_graph.py`, `backend/app/services/code_ingestion.py`,
routes in `backend/app/api/routes/knowledge.py`), which indexes source-file
symbols (functions/classes via Python `ast` and TS/JS regex), not documents or
free text, and stores nothing in a vector space. The frontend's "Knowledge"
feature (`frontend/src/app/features/knowledge/knowledge-graph.component.ts`) is
pure mock data (`MockDataService`), not wired to the real backend endpoints at
all. The only other appearances of "RAG" in the repo are two cosmetic strings
in mock data (a fake "Knowledge Agent – RAG" prompt card and a fake "Update RAG
knowledge base (OCR)" approval item) with zero backing logic.

## Evidence

- `backend/requirements.txt`: no vector DB client, no `pgvector`, no
  `sentence-transformers`/`openai`/embedding SDK, no `langchain`/`llama-index`,
  no OCR/document-parsing library. Only `fastapi`, `sqlalchemy`, `psycopg2-binary`,
  `alembic`, `neo4j`, `httpx`, `pyjwt`, `bcrypt`, `pytest`, etc.
- Full-tree grep of `backend/app` for `knowledge|embedding|chunk|vector|rag|retriev`
  returns only: `knowledge.py` (routes), `knowledge.py` (schemas),
  `knowledge_graph.py` (service), `code_ingestion.py` (service), and streaming
  "chunk" hits in `agent_runtime/adapters.py`, `task_execution.py`,
  `workflow_execution.py` — these are LLM-CLI **output stream chunks**
  (`on_chunk` callbacks for live token/line streaming), unrelated to document
  chunking.
- `backend/alembic/versions/*.py` (11 migration files): no `document`,
  `embedding`, or `vector` column/table anywhere; no `pgvector` extension
  enabled. Tables added are tasks, workflows, credentials, git integration,
  branch protection, PR/CI fields — no document or knowledge-content tables.
- `backend/app/models/*.py`: grep for `document|embedding|vector` across all
  model files returns nothing.
- `backend/app/services/code_ingestion.py`: `scan_directory()` walks a local
  path, parses Python with `ast` and TS/JS with a regex, and returns only
  `(file, symbol_name, kind, line)` tuples — no file content, docstrings, or
  README text is captured or stored. This is strictly code-symbol extraction
  for the graph, not document indexing.
- `backend/app/api/routes/knowledge.py`: four endpoints, all Neo4j-graph
  operations — `POST /projects/{id}/knowledge/sync` (tasks/workflows →
  Neo4j nodes), `GET /projects/{id}/knowledge/graph`,
  `POST /projects/{id}/knowledge/ingest-repository` (code symbols → Neo4j),
  `GET /projects/{id}/knowledge/code-graph`. None retrieve, embed, or search
  document text; none call an LLM.
- `frontend/src/app/features/knowledge/knowledge-graph.component.ts`: injects
  `MockDataService` only (`this.data.graphEntities`, `this.data.graphRelationships`);
  no `HttpClient`, no call to the real `/knowledge/*` backend routes. Node-type
  counts shown ("Code 8420", "API 432", "Test 1256") are hardcoded mock numbers.
- `frontend/src/app/features/repository-intelligence/repository-intelligence.component.ts`:
  also `MockDataService`-only; its "search"/"indexing" tabs and
  `DocumentParserService`/`OCRClient` dependency names are hardcoded demo
  strings describing a fictional sample app ("fintrix"), not functionality in
  this codebase.
- `frontend/src/app/core/mock-data.service.ts:241`: a mock prompts-catalog row
  literally named `'Knowledge Agent – RAG'` with description "Answers project
  and engineering queries usi...". This is static display data for the
  Prompts feature's mock catalog; no component, service, or route in the repo
  references or executes it.
- `frontend/src/app/features/approvals/approvals.component.ts:24`: a mock
  approval-history row `'Update RAG knowledge base (OCR)'` — same pattern,
  cosmetic only.
- `docs/` and `Software_Factory_Architecture_Decision_Log (1).md`: the ADL
  explicitly scopes "knowledge" to the Engineering/Repository Knowledge Graph
  (Neo4j) and project/organization knowledge *promotion* (approval-gated
  copying of graph-derived knowledge between projects), not a document/vector
  store. Section 10.4 ("Repository intelligence and knowledge product")
  lists, as an **open question**: "What search mix is needed across graph
  traversal, keyword search and vector retrieval?" — i.e. vector retrieval is
  explicitly deferred/undecided in the architecture doc itself, not
  implemented.

## Capability-by-capability status

| Capability | Status | Evidence |
|---|---|---|
| Document ingestion (any format: PDF/DOCX/TXT/HTML) | NOT IMPLEMENTED | No parser/loader for document formats anywhere in `backend/app`; `code_ingestion.py` only reads `.py/.ts/.tsx/.js/.jsx` source files for symbol extraction. |
| Document preprocessing | NOT IMPLEMENTED | No cleaning/normalization step exists; nothing to preprocess since no documents are ingested. |
| Chunking | NOT IMPLEMENTED | No chunking algorithm exists. All "chunk" hits in the codebase are LLM-CLI output streaming callbacks (`on_chunk` in `agent_runtime/adapters.py`), unrelated to document splitting. |
| Embedding generation | NOT IMPLEMENTED | No embedding model/provider client in `requirements.txt` or code; no embedding-producing function anywhere. |
| Vector storage (pgvector / separate vector DB) | NOT IMPLEMENTED | No `pgvector` extension in any Alembic migration; no vector DB dependency or client; PostgreSQL schema has no vector columns. |
| Semantic search | NOT IMPLEMENTED | No embedding step exists to search over; no semantic-search endpoint or function. |
| Metadata filtering (over a knowledge/document store) | NOT IMPLEMENTED | No document store exists to filter; unrelated to the Neo4j property filters used in `knowledge_graph.py` queries. |
| Hybrid retrieval | NOT IMPLEMENTED | No retrieval system of any kind (keyword or vector) over documents exists. The ADL itself lists this search mix as an open design question, not a built feature. |
| Reranking | NOT IMPLEMENTED | No retrieval pipeline exists to rerank. |
| RAG pipeline (retrieve-then-generate into an LLM call) | NOT IMPLEMENTED | `agent_runtime/adapters.py` sends a single user/task `prompt` string straight to Anthropic/OpenAI/Gemini/Qwen/CLI agents (`_run_anthropic_prompt_streaming`, etc.) with no retrieval step injecting document context beforehand. |
| Source citations | NOT IMPLEMENTED | No retrieval results exist to cite; no citation field in any schema. |
| Knowledge Graph integration point | OUT OF SCOPE (see other audit) | `backend/app/services/knowledge_graph.py`, `backend/app/api/routes/knowledge.py` — real Neo4j sync/query code exists for tasks, workflows, and code symbols. This is graph-structured engineering metadata, not document/vector knowledge; do not conflate the two. |
| Agent-accessible knowledge during execution | NOT IMPLEMENTED | `task_execution.py` / `workflow_execution.py` build the agent prompt from task/workflow fields only (see `agent_runtime/base.py`, `adapters.py`); no code path fetches graph data, documents, or any retrieved context and injects it into the prompt before execution. An agent cannot pull from a knowledge base mid-run — no such hook exists. |
| Repository documentation indexing (READMEs, docstrings) | NOT IMPLEMENTED | `code_ingestion.py`'s `_parse_python`/`_parse_ts_js` extract only symbol name/kind/line number; docstring text, comments, and README files are never read into any node property or stored anywhere. |
| Knowledge versioning (for a document/RAG store) | NOT IMPLEMENTED | No versioning exists because no document knowledge store exists. (Note: the ADL describes a *graph* snapshot/versioning concept for the Engineering KG — that is the other audit's subject.) |
| Frontend "Knowledge" UI (`features/knowledge`) | MOCKED-HARDCODED | `knowledge-graph.component.ts` uses only `MockDataService`; never calls the real `/projects/{id}/knowledge/*` backend routes that do exist. |
| "Knowledge Agent – RAG" / "RAG knowledge base" UI strings | MOCKED-HARDCODED | Static demo rows in `mock-data.service.ts:241` and `approvals.component.ts:24`; no component or service executes or references RAG logic. |

## Organizational vs. repository-specific knowledge separation

Not applicable to RAG/document knowledge: no such knowledge base exists to
separate. At the graph level (out of this audit's scope but worth flagging the
boundary), the ADL describes a project-private vs. organization-promoted model
for the *Engineering Knowledge Graph* (`knowledge_promotions`,
`knowledge_permissions` tables mentioned in the ADL) — whether that promotion
mechanism is actually implemented in code is a question for the Knowledge
Graph audit, not this one. No equivalent org/repo split exists for documents
or embeddings because no document-ingestion or vector-store code exists at
all.

## Bottom line

Every RAG-pipeline capability in scope for this audit is **NOT IMPLEMENTED**.
The only things in the codebase that use the word "knowledge" are (1) a real,
working Neo4j code/task/workflow graph feature — out of this audit's scope —
and (2) decorative mock-data strings with no backing code. There is currently
no way for a document, PDF, README, or any free-text source to be ingested,
embedded, stored in a vector space, retrieved, or fed into an LLM call as
grounding context anywhere in this system.
