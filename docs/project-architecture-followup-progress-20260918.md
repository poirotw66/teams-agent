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
| G Independent frontend + legacy removal | Partial — soft deliverables + fail-closed `delete_legacy_js.py` + empty store/`getLoadError` UI; **tree delete still waits unused release** |
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
Re-checked on local `main` tip (ahead of `origin/main` by ~140 commits):

- Adapter + Agent `ruff check`: exit 0
- `check_architecture.py`: passed (oversized files/functions empty)
- `check_legacy_shell.py`: quarantine-present mode OK
- `snapshot_openapi.py --check` + `generate_openapi_ts.py --check`: OK
- `check_wire_contracts.py`: OK
- `check_frontend_dto_overlap.py`: `handwritten_only=0`
- `check_console_openapi_matrix.py` + `check_console_bundle_budget.py`: OK
- `sync_console_v2.py --check`: OK
- console Vitest: 17 passed
- Agent full pytest: 1740 passed (fixed UTC-midnight flaky conversation-volume trend seed)
- Adapter pytest: 215 passed

`origin/main` still has **no** `static/legacy-js` / `BACKOFFICE_LEGACY_SHELL_*` (last remote tip predates quarantine). First ship of this tip starts the unused-release clock; it does **not** delete the tree in the same release.

## Goal blockers (not closed)
- **G hard exit:** `static/legacy-js` still present (~74 files / ~18k LOC). Quarantine is **not yet on origin/main**, so the unused production release cycle has not started. After that cycle: `uv run python scripts/delete_legacy_js.py --confirm-unused-release-completed --write` (updates waivers/progress; dual-mode legacy gate accepts absence).
