# Architecture Baselines

Stop-the-bleeding ratchets and Wave 0–5 governance for the project architecture
refactor plan (`docs/project-architecture-refactor-plan-20260918.md`).

## Checks (required CI)

| Command | Purpose |
|---|---|
| `uv run python scripts/check_architecture.py` | Reverse-import allowlist, monotonic file/function size ratchet, ownership importer-count ratchet |
| `uv run python scripts/check_architecture.py --write-baselines` | Full regeneration of size/import/importer-count baselines |
| `PYTHONPATH=agent_service/src uv run --directory agent_service python ../scripts/snapshot_openapi.py --check` | Verify public route + component schema inventories |
| `PYTHONPATH=../src:src uv run --directory agent_service python ../scripts/check_wire_contracts.py` | Adapter ↔ Agent wire-field compatibility |
| Golden / release / frontend steps | Named jobs in `.github/workflows/ci.yml` |

Formal oversized residuals: [`oversized-waivers.md`](./oversized-waivers.md).

## Rules

1. Domain packages must not add new reverse imports beyond `baselines/reverse_imports.json` (currently empty).
2. New production source files must stay at or below 500 lines.
3. Existing oversized files and functions may shrink, but must not grow past their baseline. Shrinks auto-tighten the baseline JSON on check (`BASELINE_TIGHTENED`); commit the rewrite.
4. Ownership edges `ai_ops_backoffice->agent_service` and `knowledge_portal->agent_service` are capped by `baselines/importer_counts.json` (must not grow).
5. Public FastAPI routes/status codes/schema names are pinned under `baselines/openapi/`.
6. `platform_kernel` holds shared ports only and must not import domain packages.
7. Optional per-symbol expiry stubs live in `baselines/size_waivers.json` (`waivers: []` is a no-op).

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
| 4 React sole product UI | Done | `/` and `/legacy` redirect to `/console-v2` unless legacy kill switch |
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
