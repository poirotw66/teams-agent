# Architecture Baselines

Stop-the-bleeding ratchets and Wave 0–5 governance for the project architecture
refactor plan (`docs/project-architecture-refactor-plan-20260918.md`).

## Checks (required CI)

| Command | Purpose |
|---|---|
| `uv run python scripts/check_architecture.py` | Reverse-import allowlist, monotonic file/function size ratchet, ownership importer-count ratchet, allowed-edge matrix, size-waiver expiry |
| `uv run python scripts/check_architecture.py --compare-ref origin/main` | Same checks plus growth-vs-ref baselines (CI uses PR base / `main`) |
| `uv run python scripts/check_architecture.py --write-baselines` | Full regeneration of size/import/importer-count baselines |
| `uv run python scripts/check_legacy_shell.py` | Defaults + deploy/env samples keep `BACKOFFICE_LEGACY_SHELL_ENABLED` off; `static/legacy-js` stays quarantine |
| `PYTHONPATH=agent_service/src uv run --directory agent_service python ../scripts/snapshot_openapi.py --check` | Verify public route + component schema inventories and the canonical Backoffice OpenAPI document (breaking-change report on drift) |
| `PYTHONPATH=agent_service/src uv run --directory agent_service python ../scripts/generate_openapi_ts.py --check` | Verify generated Console TypeScript schemas + client match the canonical OpenAPI |
| `python3 scripts/check_console_openapi_matrix.py` | Verify console_frontend literal `/api` call sites resolve in the canonical Backoffice OpenAPI |
| `python3 scripts/check_frontend_dto_overlap.py` | Fail when handwritten DTOs redefine OpenAPI-generated names |
| `python3 scripts/sync_console_v2.py --check` | Verify committed `static/console-v2` matches a fresh `console_frontend` production rebuild (hash parity) |
| `PYTHONPATH=../src:src uv run --directory agent_service python ../scripts/check_wire_contracts.py` | Adapter ↔ Agent wire-field compatibility |
| Golden / release / frontend steps | Named jobs in `.github/workflows/ci.yml` |

Formal oversized residuals: [`oversized-waivers.md`](./oversized-waivers.md).

## Rules

1. Domain packages must not add new reverse imports beyond `baselines/reverse_imports.json` (currently empty).
2. Cross-domain imports must appear on `ALLOWED_CROSS_DOMAIN_EDGES` in `scripts/check_architecture.py` (unknown edges fail with `EDGE_NOT_ALLOWED`).
3. New production source files must stay at or below 500 lines.
4. Existing oversized files and functions may shrink, but must not grow past their baseline. Shrinks auto-tighten the baseline JSON on check (`BASELINE_TIGHTENED`); commit the rewrite.
5. Ownership edges `ai_ops_backoffice->agent_service` and `knowledge_portal->agent_service` are capped by `baselines/importer_counts.json` (must not grow).
6. Public FastAPI routes/status codes/schema names are pinned under `baselines/openapi/`.
   Canonical full OpenAPI for the Console seam is
   `baselines/openapi/ai_ops_backoffice.openapi.json` (real `operationId`s + schemas).
   Generated TypeScript lives at
   `console_frontend/src/shared/api/generated/backoffice-schemas.ts` (schemas)
   and `backoffice-client.ts` (typed `backofficeClient` operation wrappers).
   After intentional API changes:
   `snapshot_openapi.py --write` then `generate_openapi_ts.py --write`.
7. Production React console assets live at
   `agent_service/src/ai_ops_backoffice/static/console-v2/` and must match
   `console_frontend` via `python3 scripts/sync_console_v2.py --check`.
   After intentional UI changes: `python3 scripts/sync_console_v2.py --write`
   and commit the refreshed hashed assets.
8. `platform_kernel` holds shared ports only and must not import domain packages.
9. Optional per-symbol waivers live in `baselines/size_waivers.json`. Empty `waivers: []` is valid; non-empty entries require owner/reason/expiry/tracking_issue/target_size and fail when `expiry` is past.
10. Legacy UI quarantine retired: `static/legacy-js/` deleted (Phase G hard exit).
   Product path remains React `/console-v2`. Dual-mode `scripts/check_legacy_shell.py`
   accepts absence; defaults + deploy/env samples must keep
   `BACKOFFICE_LEGACY_SHELL_ENABLED` off.

## Characterization suites

- `agent_service/tests/test_workbench_routes.py`
- `agent_service/tests/test_knowledge.py`
- `agent_service/tests/test_knowledge_release.py`
- `agent_service/tests/test_release_coordinator_matrix.py`
- `agent_service/tests/test_golden_baseline.py`

UI ownership: `docs/ai-ops-route-ledger.md` (30/30 ledger routes owned by React `/console-v2`).

## Wave status

| Wave | Status | Notes |
|---|---|---|
| 0 Architecture ratchet | Done | Baselines + CI |
| 1 Kernel + composition | Done | `platform_kernel/ports`, `composition/` |
| 2 HTTP / workbench application | Done | Routers under `routers/*`; use cases under `application/` |
| 3 Knowledge + Release stages | Done | `knowledge_pipeline/*` + thin `knowledge.py`; `knowledge_portal/release/*` + thin `ReleaseService` |
| 4 React sole product UI | Done | `/` and `/legacy` redirect to `/console-v2`; legacy-js tree removed |
| 5 Governance | Done | Required CI gates; oversized waivers; docs/topology aligned |

## Ports and composition

`agent_service/src/platform_kernel/ports/` defines:

- `ReleaseGateChecker` / `ReleaseGateBlockedError`
- `GovernanceProvider`
- `SourceCatalogWriter` / `SourceCatalogEntry`

Backoffice adapters: `ai_ops_backoffice/adapters/platform_ports.py`.
Composition root: `composition/`.
Backoffice bootstrap: `ai_ops_backoffice/bootstrap/` (container, repositories, error handlers, UI, route registration).

## Domain HTTP layout

Workbench, analytics, quality, console, gate, evaluation, sources, and FAQ routers
live under `ai_ops_backoffice/routers/`. Application use cases live under
`ai_ops_backoffice/application/`. Legacy `*_router.py` / `*_routes.py` files (if any)
are compatibility shims only.
