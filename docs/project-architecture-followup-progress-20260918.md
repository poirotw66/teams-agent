# Architecture Follow-up Progress (2026-09-18 session)

Tracks execution of `docs/project-architecture-post-refactor-review-20260918.md`.

## Ownership importer caps (current)
- `ai_ops_backoffice→agent_service`: **0**
- `knowledge_portal→agent_service`: **0**

## Phase status

| Phase | Status |
|---|---|
| A Required CI green | Done |
| B Composition import isolation | Done |
| C Monotonic architecture ratchet | Done |
| D Shared ownership | **Done for importer edges** — Portal=0; Backoffice=0 via composition ports/adapters |
| E HTTP/app/persistence boundaries | Done (workbench store + expanded private-access gate) |
| F Canonical OpenAPI + generated TS client | Done (schemas + typed client + CI freshness); hand-written DTO migration optional residual |
| G Independent frontend + legacy removal | Partial — independent console image + release path for UI-only builds; quarantine CI green; legacy-js delete still waits unused release cycle |
| H Oversized domain convergence | **Done for size ratchets** — 0 oversized files, 0 oversized functions |

## Goal blockers (not closed)
- **G:** `static/legacy-js` still present (~73 files). Quarantine CI green; tree delete waits one unused release cycle. UI-only release builds console image without Backoffice Python (set `GCP_CONSOLE_SERVICE` for Cloud Run cutover).
- **F residual (optional):** hand-written frontend DTOs may still parallel generated client.
