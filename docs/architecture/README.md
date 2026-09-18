# Architecture Baselines (Wave 0)

Stop-the-bleeding ratchets for the project architecture refactor plan.

## Checks

| Command | Purpose |
|---|---|
| `uv run python scripts/check_architecture.py` | Reverse-import allowlist, file-size ratchet, function-size ratchet |
| `uv run python scripts/check_architecture.py --write-baselines` | Refresh size/import baselines after intentional shrinks |
| `PYTHONPATH=agent_service/src uv run --directory agent_service python ../scripts/snapshot_openapi.py --check` | Verify public route + component schema inventories |
| `PYTHONPATH=agent_service/src uv run --directory agent_service python ../scripts/snapshot_openapi.py --write` | Refresh OpenAPI inventories after intentional API changes |

## Rules

1. Domain packages must not add new reverse imports beyond `baselines/reverse_imports.json`.
2. New production source files must stay at or below 500 lines.
3. Existing oversized files and functions may shrink, but must not grow past their baseline.
4. Public FastAPI routes/status codes/schema names are pinned under `baselines/openapi/`.
5. `platform_kernel` holds shared ports only and must not import domain packages.

## Characterization suites

These existing tests are the Wave 0 behavior baselines for later structural PRs:

- `agent_service/tests/test_workbench_routes.py`
- `agent_service/tests/test_knowledge.py`
- `agent_service/tests/test_knowledge_release.py`
- `agent_service/tests/test_pr4_release_gate_and_schedule.py`

UI migration ownership remains in `docs/ai-ops-route-ledger.md`.

## Wave 1 ports

`agent_service/src/platform_kernel/ports/` defines:

- `ReleaseGateChecker` / `ReleaseGateBlockedError`
- `GovernanceProvider`
- `SourceCatalogWriter` / `SourceCatalogEntry`

Backoffice adapters live in `ai_ops_backoffice/adapters/platform_ports.py`.
Composition root: `composition/` (agent hooks + portal app wiring).
Backoffice bootstrap: `ai_ops_backoffice/bootstrap/` (container, repositories, error handlers, UI, route registration).

## Wave 2 (in progress)

Workbench HTTP routes live under `ai_ops_backoffice/routers/workbench/` with application use cases in `application/workbench/`.
Analytics, quality, console, gate, evaluation, sources, and FAQ routers are packaged similarly; old `*_router.py` / `*_routes.py` files are compatibility shims.
Public query helpers (`resolve_source_content_excerpt`, `metrics_definitions`, `source_repository`) replace private member access from routers.

## Wave 3 (in progress)

- `agent_service/knowledge_pipeline/`: planner, candidate_policy, grounding, policy_overlay, relevance, trace, retriever helpers; `HybridKnowledgeService` remains the facade.
- `knowledge_portal/release/`: transitions, ports, coordinator skeleton; `ReleaseService` still owns the activation saga.

Analytics HTTP routes live under `ai_ops_backoffice/routers/analytics/`. Quality HTTP routes live under `ai_ops_backoffice/routers/quality/` (cases, content, candidates, gaps, clusters). Console aggregation routes live under `ai_ops_backoffice/routers/console/`; quality-gate routes under `ai_ops_backoffice/routers/gate/`. Golden evaluation-set, sources, and FAQ routes live under `routers/evaluation/`, `routers/sources/`, and `routers/faq/`. The old `analytics_router.py`, `quality_routes.py`, `console_routes.py`, `gate_routes.py`, `evaluation_routes.py`, `sources_router.py`, and `faq_routes.py` files are compatibility shims.
