# PRD / Requirement Index

Every task ID referenced by `audit/09-SOFTWARE_FACTORY_REMAINING_ROADMAP.md`, with its defining doc.
Cite the ID (e.g. "P3-3") instead of reproducing roadmap prose. Status strings here are kept
verbatim-equivalent to the roadmap's own table text — update both together if status changes.

| ID | Feature | One-line objective | Status | Defined in |
|---|---|---|---|---|
| P0-1 | Rotate placeholder secrets | Replace `SF_JWT_SECRET`/`SF_CREDENTIAL_ENCRYPTION_KEY` with real values in any non-local `.env` | DONE (structural fail-fast guard) | `09` §Phase 0 |
| P0-2 | Disable dev-login outside local dev | Turn off `SF_DEV_QUICK_LOGIN_ENABLED` for shared/staging/prod | DONE | `09` §Phase 0 |
| P0-3 | Add auth rate limiting | Throttle `/auth/login` and `/auth/register` | DONE | `09` §Phase 0 |
| P2-1 | Graph Access Service | Dedicated module all Neo4j reads/writes pass through, scope from authenticated identity | DONE | `09` §Phase 2, `04` §3.5 |
| P2-2 | Knowledge graph schema | Constraints/indexes for existing + near-term node labels | DONE | `09` §Phase 2, `04` §3.1 |
| P2-3 | Sandbox all local-CLI adapters | Route Claude Code/Codex/Gemini CLI/Qwen through Docker isolation | PARTIALLY DONE (plumbing built, off by default — no real per-CLI image yet) | `09` §Phase 2, `06` §5 |
| P2-4 | Agent Registry foundation | Minimal Agent entity (id/version/capabilities/status) | DONE (foundation only) | `09` §Phase 2, `03` §B |
| P3-1 | Test execution | Real test-runner integration surfaced in "Test Results" UI | DONE | `09` §Phase 3, `01` §D |
| P3-2 | Repository KG ↔ Git integration | Wire graph ingestion to real `RepositoryConnection`/worktree, record commit SHA | DONE | `09` §Phase 3, `04` §3.2 |
| P3-3 | Repository KG extraction breadth | Imports/dependencies/test-mapping relationships via a parser-adapter framework | **DONE — VERIFIED** (commit TBD) | `09` §Phase 3, `04` §3.2/3.6 |
| P3-4 | Multi-turn conversation | `TaskMessage` model + route + UI wiring for follow-ups | **DONE — VERIFIED** (backend; commit TBD) | `09` §Phase 3, `01` §D |
| P3-5 | Review comments | `ReviewComment` model + CRUD routes + UI wiring | DONE | `09` §Phase 3, `01` §D |
| P3-6 | Planning & Approval gate | `Plan` entity + `Approval` model/route; replace mocked frontend Approvals | DONE (Approval half only; no `Plan` entity) | `09` §Phase 3, `06` §9 |
| P4-1 | Resolve the search-mix design question | Decide graph vs. keyword vs. vector retrieval mix | DONE — local Ollama embeddings + pgvector, kept separate from the Neo4j graph (see `DECISION_REGISTER.md`) | `09` §Phase 4, `05` (Bottom line) |
| P4-2 | Document ingestion + chunking | Build ingestion/chunking pipeline for the P4-1 format(s) | DONE — plain text/Markdown content only (no PDF/DOCX/HTML) | `09` §Phase 4, `05` |
| P4-3 | Embedding + vector storage | Likely pgvector | DONE — pgvector + HNSW cosine index, local Ollama `nomic-embed-text` | `09` §Phase 4, `05` |
| P4-4 | Retrieval + RAG pipeline | Wire retrieval into `task_execution.py`'s prompt construction | DONE — `document_retrieval.py` + `_build_prompt_with_rag_context`, `/documents/search` endpoint | `09` §Phase 4, `05` |
| P5-1 | Agent orchestration layer | Supervisor/Planner, shared workflow state, task contracts, assignment ranking/escalation | NOT IMPLEMENTED | `09` §Phase 5, `03` §B |
| P5-2 | Agent replacement / handoff | Session-ID persistence, versioned handover, true resume | NOT IMPLEMENTED | `09` §Phase 5, `03` §B |
| P5-3 | Provider routing & fallback | Multi-provider candidate selection with policy-controlled fallback | NOT IMPLEMENTED | `09` §Phase 5, `03` §C |
| P5-4 | Graph-powered agent retrieval | Bounded, scoped, snapshot-pinned graph-retrieval tool callable during execution | NOT IMPLEMENTED (P3-2/P3-3 now both done — this is unblocked) | `09` §Phase 5, `04` §3.4 |
| P6-1 | Notifications | Backend model + delivery | NOT IMPLEMENTED | `09` §Phase 6, `01` §A |
| P6-2 | Audit log viewer | Frontend surface for the already-real `AuditLog` data | NOT IMPLEMENTED (frontend); BACKEND ONLY today | `09` §Phase 6, `06` §8 |
| P6-3 | Cost tracking & execution tracing | Parse/store provider usage fields; structured trace/span model | NOT IMPLEMENTED | `09` §Phase 6, `03` §C |
| P6-4 | Prompt injection / output safety | Output-scanning step before task output is persisted/displayed | NOT IMPLEMENTED | `09` §Phase 6, `06` §4/§10 |

## Dependency notes (from `09`'s own sequencing)

- P3-2 depends on P2-1/P2-2. P3-3 depended on P3-2 — both now done.
- P5-4 was **hard-gated** on P3-2 and P3-3; both are done, so P5-4 can now be scheduled.
- P5-1 depends on P2-4 (done, unblocked).
- P4-1 resolved; P4-2–P4-4 built on that decision (done).
- Phase 6 items are fully independent/parallel to everything else.

## Source docs key

`01`=CURRENT_STATE, `02`=ARCHITECTURE, `03`=AGENT_ORCHESTRATION_AUDIT, `04`=REPOSITORY_KNOWLEDGE_GRAPH_AUDIT,
`05`=RAG_AND_KNOWLEDGE_AUDIT, `06`=SECURITY_AND_GOVERNANCE_AUDIT, `07`=TESTING_AND_VERIFICATION_REPORT,
`08`=IMPLEMENTATION_GAP_ANALYSIS, `09`=SOFTWARE_FACTORY_REMAINING_ROADMAP, `10`=ENGINEERING_HANDOVER_SUMMARY,
`11`=IMPLEMENTATION_CHANGELOG — all under `audit/`.
