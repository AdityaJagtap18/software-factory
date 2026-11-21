# Next Actions — Context Handover

Update this file at the end of every implementation milestone so another agent (or a future me) can
continue without re-auditing the repo. Replace the content below each time — this is current state,
not a log (the log is `audit/11-IMPLEMENTATION_CHANGELOG.md`).

---

## Current phase

Phase 4 (RAG / Document Knowledge) is **DONE**. Phase 5 (Multi-Agent Orchestration & Graph-Powered
Retrieval) has not started. See `audit/09-SOFTWARE_FACTORY_REMAINING_ROADMAP.md` §Phase 5 for full
scope; `PRD_REQUIREMENT_INDEX.md` for the task-ID table (P5-1..P5-4).

Note: Phase 3's P3-3 (Repository KG extraction breadth) is also still open and unblocked (its
dependency, P3-2, is done) — it is not part of Phase 5 but is available to pick up independently.
P5-4 is hard-gated on P3-3 landing first (per the roadmap's own dependency note), so P3-3 should
likely be picked up before or alongside P5-1..P5-3.

## Completed tasks

- Phase 0 (security hygiene) — commit `89a9f51`
- Phase 2 (graph access, schema, sandbox plumbing, agent registry) — commit `c20000c`
- Phase 3 (test execution, commit-SHA provenance, review comments, approvals) — commit `6f21376`
- Persistent context scaffolding: `PROJECT_CONTEXT.md`, `IMPLEMENTATION_STATE.md`,
  `PRD_REQUIREMENT_INDEX.md`, `DECISION_REGISTER.md`, `NEXT_ACTIONS.md` (this file) at repo root.
- Phase 4 (P4-1 search-mix decision, P4-2 document ingestion/chunking, P4-3 pgvector + local Ollama
  embeddings, P4-4 retrieval + RAG wired into `task_execution.py`) — see `IMPLEMENTATION_STATE.md`
  and `DECISION_REGISTER.md` for the commit SHA and full decision rationale.

## Remaining tasks

- P3-3 (available now, not gated)
- P3-4 re-verification (flagged as "appears implemented, not re-verified")
- Phase 5 (P5-1..P5-4) — P5-4 hard-gated on P3-3
- Phase 6 (P6-1..P6-4) — fully independent, can run any time
- Not built in Phase 4 (left explicitly out of scope, not forgotten): PDF/DOCX/HTML document
  ingestion, OCR, reranking, a frontend UI for document upload/search/citations (the existing
  `knowledge-graph.component.ts`/`repository-intelligence.component.ts` remain 100% mock-data and
  were not touched)

## Files changed (this milestone — Phase 4)

Backend: `app/models/document.py` (new), `app/schemas/document.py` (new),
`app/services/document_chunking.py` (new), `app/services/embeddings.py` (new),
`app/services/document_retrieval.py` (new), `app/api/routes/documents.py` (new),
`alembic/versions/8a0dcf3b06fb_*.py` (new migration — `CREATE EXTENSION vector`, `documents`/
`document_chunks` tables, HNSW cosine index), `app/models/__init__.py` (+Document/DocumentChunk,
isolated from pre-existing uncommitted repository_intelligence changes), `app/main.py`
(+documents router, isolated), `app/services/task_execution.py` (+`_build_prompt_with_rag_context`,
isolated from pre-existing uncommitted model-resolution/knowledge-context refactor — see
`DECISION_REGISTER.md` for why this file needed special handling), `requirements.txt` (+pgvector),
`tests/conftest.py` (+`CREATE EXTENSION IF NOT EXISTS vector` for the test DB).
Infra: `docker-compose.yml` (postgres image → `pgvector/pgvector:pg16`, isolated from a pre-existing
uncommitted `SF_GEMINI_API_KEY` env addition in the same file).
Tests: `tests/test_document_chunking.py` (new, 4 cases), `tests/test_documents.py` (new, 7 cases).

## Tests executed and results

Full suite: **182 passed, 14 failed** (`pytest -q`, ~229s). The 14 failures are the same
pre-existing, unrelated set as every prior phase (stale `model=` kwarg mismatch in test fixtures —
see Known issues). Zero regressions; the 10 new passing tests are exactly what this milestone added.
Also verified live via curl against the running dev backend: real document ingestion → real
`nomic-embed-text` embedding → real pgvector cosine-similarity search returning the correct document
with a genuine similarity score (0.7174) for a semantically related (not keyword-identical) query.

## Known issues

- 14 pre-existing test failures from a stale `model=` kwarg mismatch in test fixtures
  (`test_agent_runtimes.py`/`test_tasks.py`/`test_workflows.py`), tied to already-uncommitted
  model-selection work elsewhere in the tree. Not caused by any phase; do not attempt to fix as part
  of an unrelated phase's scope.
- P2-3 sandboxing is inert (no real per-CLI Docker image configured).
- P3-4 (multi-turn conversation) status is unverified, not confirmed broken or confirmed working.
- Phase 4's document ingestion only accepts plain text/Markdown via a JSON API body — there is no
  file-upload endpoint and no PDF/DOCX/HTML parser. This is a deliberate scope decision (see
  `DECISION_REGISTER.md`), not a gap to silently work around.
- If the local Ollama instance (`OLLAMA_HOST`, default `http://127.0.0.1:11434`) doesn't have
  `nomic-embed-text` pulled, every embedding call fails honestly with `EmbeddingError` (503 on the
  ingest/search routes) rather than fabricating a vector. Run `ollama pull nomic-embed-text` against
  that host if this shows up in a fresh environment.

## Architectural decisions

See `DECISION_REGISTER.md` for the full list with Why/Implication, including this milestone's new
top entry (P4-1's resolution).

## Exact next implementation task

Pick up **P3-3** (Repository KG extraction breadth — imports/dependencies/test-mapping relationships
via a parser-adapter framework): read `audit/04-REPOSITORY_KNOWLEDGE_GRAPH_AUDIT.md` §3.2 and §3.6
("Proposed implementation sequence," step 5) for the already-worked-out dependency-ordered approach.
Its prerequisite P3-2 is done. Doing this before Phase 5 also unblocks P5-4 (graph-powered agent
retrieval), which is hard-gated on it. Alternatively, Phase 5 items P5-1/P5-2/P5-3 have no blocking
dependency left and could be started in parallel if resourcing allows.
