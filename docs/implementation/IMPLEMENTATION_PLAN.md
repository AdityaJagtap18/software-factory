# Implementation Plan (Stage 0 output)

## Scope of this pass

Build the Angular UI shell: a real, routed, componentized Angular application
recreating all 14 reference screens, using the supplied design system and SVG
assets, backed by mock data services (clearly marked as such) so every screen
is navigable and interactive. No backend, no database, no real agent
integration in this pass — those are out of scope for a single UI-focused
session and are deferred to later phases per the architecture's own
phase-gated roadmap (Phase 0/1 backend work).

## Steps

1. Scaffold Angular app (`frontend/`) with routing, SCSS, strict mode.
2. Design tokens: CSS custom properties for the navy/blue/violet palette,
   spacing, radii, shadows, typography — derived from the reference images and
   SVG README.
3. Copy SVG asset pack into `frontend/src/assets/`.
4. App shell: sidebar nav (icons from asset pack), top bar (search,
   notifications, user menu), organization selector, router outlet.
5. Build each of the 14 pages as its own routed feature component, using mock
   data services for lists/metrics/status so the UI is populated and
   interactive (sorting/filtering/navigation where the reference implies it),
   not a static image.
6. Verify each page in the browser against its reference screenshot for
   layout/spacing/color fidelity.

## Explicitly deferred (not built this pass)

- FastAPI control plane, PostgreSQL, Neo4j, Redis, Temporal, LangGraph, Docker
  execution — all backend/infra layers.
- Real Codex / Claude Code / Local Agent Bridge integrations.
- Auth (login screen is built and navigable; it does not authenticate against
  a real identity provider).
- Any write path that would mutate real data — all data in this pass is
  client-side mock data, visibly so in code (`*.mock.ts` / mock services).

## Definition of done for this pass

- `ng build` succeeds.
- All 14 routes render without console errors.
- Sidebar navigation, page routing, and basic in-page interactions (tabs,
  table sorting/filtering where shown in references, modals/wizards where the
  reference implies them) work using mock data.
- Visual comparison against each reference image for layout fidelity.
