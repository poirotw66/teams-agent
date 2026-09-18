# Architecture Follow-up Progress (2026-09-18 session)

Tracks execution of `docs/project-architecture-post-refactor-review-20260918.md`.

## Completed this session

### Phase A — Required CI green
- Adapter + Agent Service Ruff exit 0; facade `__all__` restored; httpx patches retargeted.
- Verified architecture, OpenAPI, wire, frontend, full pytest suites earlier in session.

### Phase B — Composition import side effects
- Inert `composition/__init__.py`; `*_asgi.py` singletons; domain `api.py` without module `app`.
- `test_composition_import_isolation.py` added.

### Phase C — Monotonic architecture ratchet
- Size baselines auto-tighten; ownership importer-count ratchet.

### Phase D — Shared ownership
- `operations_core`: access, contracts, masking, masking_rules, usage/pricing helpers.
- `knowledge_core`: release gate/pointers, target manifest, front-matter, artifacts,
  chunking profile, eligibility, document chunks/layout, artifact ports, File Search ACL.
- Portal ports + composition Agent adapters → **Portal→Agent = 0**.
- Backoffice→Agent importer files **107 → 52 → 32 → 28 → 24 → 20**.

### Phase E — Application / persistence boundaries
- Workbench JSON store; public query/source/export/policy accessors; AST private-access gate.

### Phase F — Canonical OpenAPI + generated TS (first slice)
- Canonical Backoffice OpenAPI + breaking-change report + generated TS schemas + CI freshness.

### Phase G — Independent frontend deliver (first slice)
- `sync_console_v2.py` hash gate for committed `static/console-v2`.

### Phase H — Oversized domain convergence
- `draft_assets` / `export_service` / `eval_runtime` (1018→562) / `evaluation repository` (975→330).
- `evaluation_domain/runner.py` (973→478): extracted retrieval / multi-turn / side-execution helpers.

## Still open (goal continues)

| Phase | Status |
|---|---|
| D Backoffice→Agent (20 files) | In progress — remaining: audit/scope/taxonomy/stores, document_authorization, eval/graph wiring, artifacts |
| D Portal→Agent | **Done (0)** |
| E polish beyond hotspot paths | Mostly done |
| F full TS client + DTO migration | First slice done |
| G legacy-js removal / independent deploy | First slice done |
| H more oversized offenders | Continues |

Repository strategy: modular monorepo; no physical repo split.

Current ownership importer caps:
- `ai_ops_backoffice→agent_service`: **20**
- `knowledge_portal→agent_service`: **0**
