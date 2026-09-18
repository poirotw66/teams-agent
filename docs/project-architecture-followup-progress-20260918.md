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
| G Independent frontend + legacy removal | Partial — independent console image + cloudbuild/compose; quarantine CI green; legacy-js delete + UI-only deploy cutover still open |
| H Oversized domain convergence | **File ratchet cleared** (0 files >500); **function ratchet cleared** (0 functions >80; was 18 this pass, ~39 earlier in session) |

## Goal blockers (not closed)
- **G:** `static/legacy-js` still present (~73 files). Quarantine CI is green; tree delete waits one unused release cycle. Console has independent Docker image, but release still rebuilds Backoffice Python image for UI-only changes.
- **H:** 0 oversized *files*; **0** oversized *functions* remain under the function ratchet.
- **F residual (optional):** hand-written frontend DTOs may still parallel generated client.
