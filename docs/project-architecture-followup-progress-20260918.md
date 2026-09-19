# Architecture Follow-up Progress (2026-09-18 session)

Tracks execution of `docs/project-architecture-post-refactor-review-20260918.md`.

## Ownership importer caps (current)
- `ai_ops_backoffice→agent_service`: **0**
- `knowledge_portal→agent_service`: **0**

## Phase status

| Phase | Status |
|---|---|
| A Required CI green | Done — OpenAPI snapshot builds via composition factories (adapters configured) |
| B Composition import isolation | Done |
| C Monotonic architecture ratchet | Done — size shrink + **ALLOWED_CROSS_DOMAIN_EDGES** + importer caps + **waiver expiry** + **`--compare-ref` baseline-from-main** |
| D Shared ownership | **Done for importer edges** — Portal=0; Backoffice=0 via composition ports/adapters |
| E HTTP/app/persistence boundaries | Done — private-access empty; router FS gate; **workbench Path/JSON behind WorkbenchRepository** |
| F Canonical OpenAPI + generated TS client | **Done** — schemas/client/CI freshness + consumer contracts + call-site matrix; **handwritten_only=0** (incl. portal workbench DTOs) |
| G Independent frontend + legacy removal | **Done** — soft deliverables + `static/legacy-js` removed (pre-first-ship; never on origin/main) |
| H Oversized domain convergence | **Done for size ratchets** — 0 oversized files/functions; characterization registry covers extractor/evaluation/source/documents/composition/contracts/**quality/FAQ/settings**/release matrix |

## Phase G soft deliverables (landed)
- Independent console Docker image + Cloud Build + UI-only release path (`BUILD_CONSOLE`)
- Synced `static/console-v2/*` selects console image only (not Backoffice Python)
- `Dockerfile.backoffice` is Python-only (committed console-v2 artifact; no Node stage)
- Legacy frontend characterization tests moved to `tests/legacy_frontend/` (CI skips when tree deleted)
- Deletion readiness reporter: `scripts/check_legacy_deletion_readiness.py`
- Legacy shell route characterization quarantined under `tests/legacy_frontend/` (skips when tree deleted)
- Route-level `React.lazy` + Suspense in `App.tsx`
- Vite `manualChunks` (antd / react / refine / markdown / vendor)
- Workbench store split into domain slices (`storeCore` + overview/conversations/tickets/faqs/documents)
- Synced `static/console-v2` artifact; entry gzip ~17 KiB (was ~633 KiB single bundle)
- Bundle budget gate enforces entry/feature/vendor gzip ceilings
- Vitest + Testing Library: markdown/citation/store loading/auth session behavioral tests
- Workbench store starts empty (no mock seeding); `getLoadError()` surfaces total/partial fetch failures
- Backoffice domain `import *` wildcards cleared (explicit imports)
- Product HTML no longer imports `/static/legacy-js/` (`knowledge-ui` uses `/static/js/session_auth.js`; CI enforces)
- JWT/session helpers live under `/static/js/session_auth.js`; legacy `api.js` re-exports them; reliability tests no longer import legacy-js
- Legacy shell HTML moved into `static/legacy-js/index.html` (product static root has no legacy HTML)
- Console↔OpenAPI call-site matrix gate: `scripts/check_console_openapi_matrix.py`
- Fail-closed delete helper: `scripts/delete_legacy_js.py` (requires unused-release acknowledgment)
- Dual-mode legacy shell CI gate: passes with quarantine present **or** fully removed

## Tip verification (2026-09-19)
Re-checked on local `main` tip (ahead of `origin/main`):

- Adapter + Agent `ruff check`: exit 0
- `check_architecture.py`: passed (oversized files/functions empty; allowed-edge + waiver expiry)
- `check_legacy_shell.py`: **legacy-js fully removed** (Phase G hard exit)
- `check_legacy_deletion_readiness.py`: BLOCKERS none
- OpenAPI / DTO / matrix / bundle / sync / Vitest: green on tip before delete; re-verify post-delete below

Phase G hard exit used `--confirm-never-shipped-to-origin` because `origin/main` never contained quarantine / `BACKOFFICE_LEGACY_SHELL_*`.

## Goal blockers (not closed)

- None — Phase G hard exit complete (`static/legacy-js` absent).
