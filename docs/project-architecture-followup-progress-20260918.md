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
| D Shared ownership (`operations_core` / `knowledge_core`) | Done for ownership importers — Portal=0; Backoffice=0 (Agent wiring via composition ports: chat model, answer prompt, HybridIndex, eval Agent bindings, policy runtime, ops/GCS collaborators) |
| E HTTP/app/persistence boundaries | Done for hotspot paths + expanded private-access gate (services/application/governance; eval_* excluded) |
| F Canonical OpenAPI + generated TS client | Done first+second slice (schemas + typed client + CI freshness) |
| G Independent frontend + legacy removal | Bundle sync gate + legacy-shell quarantine CI; full `legacy-js` delete pending unused cycle |
| H Oversized domain convergence | Ongoing (eval runtime/repo/runner, quality service, gate repos, draft/export) |

## Remaining Backoffice→Agent importers (0)
Cleared this slice: `eval_prompt`, `wiring`, `real_rag_adapters`, `eval_fixtures`, `eval_flow`, `eval_runtime` — all Agent construction moved behind Backoffice ports registered by `composition/backoffice_agent_adapters.py` / `backoffice_eval_agent_factory.py`.
