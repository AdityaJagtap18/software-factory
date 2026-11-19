# Reference Inventory (Stage 0)

## UI reference images (`UI reference/`)

| File | Maps to page |
|---|---|
| LoginReffreance.png | Login |
| Daskboard.png | Factory Dashboard |
| Project WorkSpace.png | Project Workspace |
| Workflow.png | Workflow Visualizer |
| Agent Command Center.png | Agent Command Center |
| KnowlageGraph.png | Knowledge Graph Explorer |
| repoIntelligance.png | Repository Intelligence |
| Task Workspace.png | Task Workspace / Coding Agent |
| Code Changes & Review.png | Code Changes & Review |
| Approval Center.png | Approval Center |
| Monitoring & Observability.png | Monitoring & Observability |
| Provider & Model Management.png | Provider & Model Management |
| Promt Registry.png | Prompt Registry |
| Settings.png | Settings / Coding Agent Configuration |

All 14 expected reference screens are present. No duplicates, no missing pages.

## Design system observed across references

- Deep navy sidebar/hero surfaces: `#14264D` / `#0C1B3F` range.
- Primary accents: blue `#2478E8`, violet `#7467FF`; light blue `#BFCBFF` for
  tints.
- White/neutral content surfaces, subtle borders, restrained shadows, rounded
  cards (~10–12px radius).
- Sidebar nav icons at ~20px, consistent spacing, active item has a filled
  violet/blue pill background.
- Status pills (green/blue/amber dot + label) used throughout for
  Active/In Progress/Healthy states.
- Data tables with light header row, hover rows, "View All →" links on card
  headers.
- Typography: bold sans-serif headings, system/Inter-like body font.

## SVG asset pack (`Software_Factory_SVG_Assets.zip` → `svg-assets-extracted/`)

- `logos/`: product mark, wordmark (regular + white), mono mark.
- `icons/navigation/`: dashboard, projects, repositories, workflows, agents,
  knowledge, artifacts, approvals, monitoring, settings, tasks, providers.
- `icons/workspace/`: code-diff, code-search, dependencies, graph-history,
  impact-analysis, indexing, pull-request, repository-graph, terminal.
- `icons/agents/`: coding, documentation, planning, review, supervisor,
  testing agent icons.
- `icons/status/`: success, warning, error, running, pending.
- `icons/providers/`: cloud-provider, local-model, model-routing.
- Convention: 24x24 viewBox, stroke `#243B73`, 1.8 stroke width, overridable
  via CSS `color`.

Copied verbatim into `frontend/src/assets/icons/` and `frontend/src/assets/logos/`
preserving folder structure, per the README's usage instructions.

## Architecture documents

- `# Software Factory.txt` — baseline spec: 9 logical layers, multi-tenant
  hierarchy, provider adapter pattern, Neo4j dual-graph model, phase-gated
  roadmap (Phase 0–6).
- `Software_Factory_Architecture_Decision_Log (1).md` — Domains 1–8 finalized;
  confirms Angular/FastAPI/LangGraph/Temporal/PostgreSQL/Neo4j/Redis/Docker
  stack, and explicitly recommends a thin vertical slice starting with the
  Angular shell (§11.1) before building out backend orchestration.

No conflicts found between the two documents; the decision log refines and
narrows the baseline spec without contradicting it.
