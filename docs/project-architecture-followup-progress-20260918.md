# Architecture Follow-up Progress (2026-09-18 session)

Tracks execution of `docs/project-architecture-post-refactor-review-20260918.md`.

## Ownership importer caps (current)
- `ai_ops_backoffice→agent_service`: **9**
- `knowledge_portal→agent_service`: **0**

## Phase status

| Phase | Status |
|---|---|
| A Required CI green | Done |
| B Composition import isolation | Done |
| C Monotonic architecture ratchet | Done |
| D Shared ownership (`operations_core` / `knowledge_core`) | In progress — Portal=0; Backoffice 9 remain (eval/graph/wiring); OpsSettings + Firestore client + pricing path helpers in `operations_core`; query_service cleared via Protocol injection from wiring |
| E HTTP/app/persistence boundaries | Done for hotspot paths + expanded private-access gate (services/application/governance; eval_* excluded) |
| F Canonical OpenAPI + generated TS client | Done first+second slice (schemas + typed client + CI freshness) |
| G Independent frontend + legacy removal | Bundle sync gate + legacy-shell quarantine CI; full `legacy-js` delete pending unused cycle |
| H Oversized domain convergence | Ongoing (eval runtime/repo/runner, quality service, gate repos, draft/export) |

## Remaining Backoffice→Agent importers (9)
`eval_prompt`, `wiring`, `baseline_judge`, `real_rag_adapters`, `eval_fixtures`, `eval_flow`, `eval_runtime`, `service_helpers`, `prompt_domain/service`.

Cleared this slice: `query_service` (OpsSettings → `operations_core`; ops runtime + GCS artifact storage injected via wiring collaborators).
