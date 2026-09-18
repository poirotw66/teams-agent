# Architecture Follow-up Progress (2026-09-18 session)

Tracks execution of `docs/project-architecture-post-refactor-review-20260918.md`.

## Completed this session

### Phase A — Required CI green
- Adapter + Agent Service Ruff exit 0 (859 → 0), including F821 / B023 / RUF012.
- Restored intentional facade re-exports via `__all__` (`extractor`, `draft_assets`, `source_models`, domain `__init__` packages).
- Retargeted httpx test patches to `query_health` / `query_knowledge` after facade cleanup.
- Verified: architecture, OpenAPI, wire, frontend node tests, Adapter 213 pytest, Agent 1708 pytest.

### Phase B — Composition import side effects
- `composition/__init__.py` no longer eager-imports app factories.
- Factories stay in `*_app.py`; ASGI singletons live in `*_asgi.py`.
- Domain `api.py` modules no longer build module-level `app`.
- Service mains point at `composition.*_asgi:app`.
- Added `tests/test_composition_import_isolation.py` (5 tests).

### Phase C — Monotonic architecture ratchet
- Size baselines auto-tighten on shrink (`BASELINE_TIGHTENED`).
- Ownership importer-count ratchet: `docs/architecture/baselines/importer_counts.json`
- `extractor.py` baseline 978 → 799; shrinks cannot silently re-grow to old caps.
- Wave0 architecture tests cover shrink-then-regrow.

### Phase D (partial) — `operations_core` first slice
- New package `operations_core` owns `ActorContext` / `CAPABILITIES` / `BackofficeRole`.
- `agent_service.operations.access` is a compatibility re-export.
- 55 Backoffice files that only needed access contracts now import `operations_core`.
- Importer-count ratchet tightened: `ai_ops_backoffice→agent_service` 107 → 52.

### Phase E (partial) — Workbench persistence boundary
- Added `ai_ops_backoffice.adapters.workbench_json_store.WorkbenchJsonStore`.
- Removed router-package JSON filesystem I/O (`routers/workbench/persistence.py` deleted).
- Workbench routes/tests green.

## Still open (goal continues)

| Phase | Status |
|---|---|
| D `knowledge_core` + remaining Agent implementation imports | Pending |
| E private-member access AST gate + source public query service | Pending |
| F canonical OpenAPI + generated TS client | Not started |
| G independent frontend deliver + legacy removal | Not started |
| H residual oversized domains | Not started |

Repository strategy unchanged: modular monorepo; no physical repo split yet.

Current ownership importer caps:
- `ai_ops_backoffice→agent_service`: **52**
- `knowledge_portal→agent_service`: **18**
