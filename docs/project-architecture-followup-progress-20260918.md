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
| G Independent frontend + legacy removal | Partial — image/UI-only release/bundle budget/code-split/Vitest foundation done; **legacy-js delete still waits unused release cycle** |
| H Oversized domain convergence | **Done for size ratchets** — 0 oversized files, 0 oversized functions |

## Phase G soft deliverables (landed)
- Independent console Docker image + Cloud Build + UI-only release path (`BUILD_CONSOLE`)
- Synced `static/console-v2/*` selects console image only (not Backoffice Python)
- Route-level `React.lazy` + Suspense in `App.tsx`
- Vite `manualChunks` (antd / react / refine / markdown / vendor)
- Synced `static/console-v2` artifact; entry gzip ~17 KiB (was ~633 KiB single bundle)
- Bundle budget gate enforces entry/feature/vendor gzip ceilings
- Vitest + Testing Library: markdown/citation/store loading/auth session behavioral tests

## Goal blockers (not closed)
- **G hard exit:** `static/legacy-js` still present (~73 files). Quarantine CI green; tree delete waits one unused release cycle. Goal cannot complete until legacy application LOC is zero.
- **F residual (optional):** hand-written frontend DTOs may still parallel generated client.
