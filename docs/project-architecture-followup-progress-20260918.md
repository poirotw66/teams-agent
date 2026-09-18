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
- Backoffice→Agent importer files **107 → 52 → 32 → 28 → 24 → 20 → 18 → 17 → 13**.
- Scope event filtering (`filter_events_by_scope` + helpers) + `TaxonomyLookup`
  Protocol live in `operations_core`; Agent `operations.scope` is a facade.
- Security-policy catalog + marker matching (`SECURITY_POLICIES`,
  `known_policy_ids_in_text`) live in `operations_core`; Agent
  `security_policies` keeps Citation / advisory builders as a facade.
  Workbench `citations.py` retargeted off Agent.
- `AuditStore` Protocol + `build_audit_event` live in `operations_core.audit`;
  Agent keeps `build_audit_store` + store backends as a facade.
- `TaxonomyRepository` lives in `operations_core.taxonomy`; Agent facade retained.
  Pricing / export / query_audit / query_helpers retargeted; query_service
  uses `knowledge_core` local artifact storage (GCS still Agent-backed).

### Phase E — Application / persistence boundaries
- Workbench JSON store; public query/source/export/policy accessors; AST private-access gate.

### Phase F — Canonical OpenAPI + generated TS (second slice)
- Canonical Backoffice OpenAPI + breaking-change report + generated TS schemas + CI freshness.
- Typed `backofficeClient` operation wrappers (`backoffice-client.ts`) from the same
  generator (`generate_openapi_ts.py --write` / `--check`). Optional consumer example:
  `dataProvider` work-items list.

### Phase G — Independent frontend deliver (first slice)
- `sync_console_v2.py` hash gate for committed `static/console-v2`.

### Phase G — Legacy shell removal path (second slice)
- `scripts/check_legacy_shell.py`: defaults keep kill-switch off; deploy/env
  samples must not enable `BACKOFFICE_LEGACY_SHELL_ENABLED`; documents
  `static/legacy-js` as quarantine (tree not deleted yet).
- CI step + architecture README / waiver deletion criteria: one release cycle
  unused, then delete quarantine + `/legacy` serve path.

### Phase H — Oversized domain convergence
- `draft_assets` / `export_service` / `eval_runtime` (1018→562) / `evaluation repository` (975→330).
- `evaluation_domain/runner.py` (973→478): extracted retrieval / multi-turn / side-execution helpers.
- `quality_domain/service.py` (902→713): extracted `clustering.py` + `case_ops.py`; facade kept.
- `evaluation_domain/gate_repository.py` (840→282): extracted file / Firestore adapters; facade kept.

## Still open (goal continues)

| Phase | Status |
|---|---|
| D Backoffice→Agent (13 files) | In progress — remaining: eval/graph wiring, artifacts GCS, prompts, freshness, firestore repos |
| D Portal→Agent | **Done (0)** |
| E polish beyond hotspot paths | Mostly done |
| F full TS client + DTO migration | Client generated; DTO migration still open |
| G legacy-js removal / independent deploy | First + second slice (quarantine gate); tree delete deferred one release cycle |
| H more oversized offenders | Continues |

Repository strategy: modular monorepo; no physical repo split.

Current ownership importer caps:
- `ai_ops_backoffice→agent_service`: **13**
- `knowledge_portal→agent_service`: **0**
