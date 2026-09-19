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
| F Canonical OpenAPI + generated TS client | Done for schemas/client/CI freshness + exact DTO re-exports; consumer-driven console contracts added; 19 workbench-only handwritten DTOs remain until OpenAPI covers them |
| G Independent frontend + legacy removal | Partial — image/UI-only release/code-split/Vitest/store lazy-load done; **legacy-js delete still waits unused release cycle** |
| H Oversized domain convergence | **Done for size ratchets** — 0 oversized files, 0 oversized functions |

## Phase G soft deliverables (landed)
- Independent console Docker image + Cloud Build + UI-only release path (`BUILD_CONSOLE`)
- Synced `static/console-v2/*` selects console image only (not Backoffice Python)
- `Dockerfile.backoffice` is Python-only (committed console-v2 artifact; no Node stage)
- Route-level `React.lazy` + Suspense in `App.tsx`
- Vite `manualChunks` (antd / react / refine / markdown / vendor)
- Synced `static/console-v2` artifact; entry gzip ~17 KiB (was ~633 KiB single bundle)
- Bundle budget gate enforces entry/feature/vendor gzip ceilings
- Vitest + Testing Library: markdown/citation/store loading/auth session behavioral tests
- Backoffice domain `import *` wildcards cleared (explicit imports)
- Product HTML no longer imports `/static/legacy-js/` (`knowledge-ui` uses `/static/js/session_auth.js`; CI enforces)
- JWT/session helpers live under `/static/js/session_auth.js`; legacy `api.js` re-exports them; reliability tests no longer import legacy-js

## Goal blockers (not closed)
- **G hard exit:** `static/legacy-js` still present (~73 files / ~18k LOC). Quarantine is **not yet on origin/main**, so the unused production release cycle has not started. Tree delete waits one unused release after quarantine ships. Product/test paths no longer require legacy-js modules.
- **F residual:** 19 workbench-domain DTOs in `types.ts` still lack OpenAPI-generated counterparts (gated against new name collisions).
