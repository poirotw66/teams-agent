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

### Phase D — Shared ownership slices
- `operations_core` owns `ActorContext` / `CAPABILITIES` / `BackofficeRole` (Backoffice→Agent 107 → 52).
- `knowledge_core` first + second slices:
  - release gate, target-manifest hashing, front-matter, artifact path constants
  - release pointers, source identity, generation eligibility, `ChunkingProfile`
- `knowledge_core` third slice (Portal importer 9 → 5):
  - `DocumentChunk` / markdown chunking (layout path stays Agent via callback)
  - artifact models + `ArtifactStorage` protocol + local-file storage
  - pure release-artifact validators
  - File Search ACL encoding
  - Portal GCS dual-write wired through composition provider (no Portal→Agent import)
- Portal→Agent importer files **18 → 9 → 5**.
- Agent modules keep compatibility facades.

### Phase E — Application / persistence boundaries
- Workbench JSON I/O behind `WorkbenchJsonStore` (earlier).
- Public APIs: `QueryService.source_trace` / `runtime_settings`, `SourceTraceResolver.active_release_id()`,
  `ExportJobService.store_path`, `PolicyRuntime.settings`.
- AST cross-module private-access gate under Backoffice `routers/` and `bootstrap/`.

### Phase F — Canonical OpenAPI + generated TS (first slice)
- Canonical artifact: `docs/architecture/baselines/openapi/ai_ops_backoffice.openapi.json`
- Breaking-change classifier in `scripts/openapi_contract.py` (reported on canonical drift)
- Generated TS schemas: `console_frontend/src/shared/api/generated/backoffice-schemas.ts`
- CI: `snapshot_openapi.py --check` + `generate_openapi_ts.py --check`
- Still open: full TS client (paths/operations), migrate hand-written DTOs, consumer-driven tests, cross-version matrix, portal/agent canonical docs

### Phase G — Independent frontend deliver + legacy removal (first slice)
- `scripts/sync_console_v2.py --write` / `--check`: rebuild `console_frontend` and gate
  SHA-256 parity of committed `ai_ops_backoffice/static/console-v2/`
- CI `console-frontend` job runs helper unit tests + freshness check (no Agent Python runtime)
- Docs: `console_frontend/README.md` + architecture baseline checklist
- Still open: independent frontend image/artifact/deploy/rollback, store/API domain split,
  behavioral component tests, route code splitting / bundle budget, delete `static/legacy-js`

## Still open (goal continues)

| Phase | Status |
|---|---|
| D remaining Portal→Agent implementation imports (5 files) | In progress |
| E broader private-access / source query service polish | Mostly done for hotspot paths |
| F canonical OpenAPI + generated TS client | First slice started: canonical Backoffice OpenAPI + TS schemas + CI freshness |
| G independent frontend deliver + legacy removal | First slice started: bundle sync script + CI hash freshness gate |
| H residual oversized domains | Not started |

Repository strategy unchanged: modular monorepo; no physical repo split yet.

Current ownership importer caps:
- `ai_ops_backoffice→agent_service`: **52**
- `knowledge_portal→agent_service`: **5**

Remaining Portal→Agent importers:
`draft_retrieval.py`, `pdf_convert_jobs.py`, `persistent_pdf_jobs.py`,
`publisher.py`, `services/document_service.py`.
