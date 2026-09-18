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
| D Shared ownership | **Done for importer edges** — Portal=0; Backoffice=0 via composition ports/adapters |
| E HTTP/app/persistence boundaries | Done (workbench store + expanded private-access gate) |
| F Canonical OpenAPI + generated TS client | Done (schemas + typed client + CI freshness); hand-written DTO migration optional residual |
| G Independent frontend + legacy removal | Bundle sync + legacy-shell quarantine CI; full `legacy-js` tree delete pending unused release cycle |
| H Oversized domain convergence | Ongoing — ~27 oversized files remain (was ~36); continue workflow/query/eval residuals |

## Recent Phase H wins
- `faq_domain/service.py` 865→436 (`transitions`, `lifecycle_ops`)
- `teams_agent/source_routes.py` 916→255 (`source_route_auth/payloads/streaming`)
- `teams_agent/source_links.py` 866→354 (`source_link_signing`, `source_link_access`)
- `evaluation_domain/gate_service.py` 821→457 (`gate_policy_ops`, `gate_release_ops`, `gate_case_ops`)
- `governance_routes.py` 844→499 (`route_models`, `search_ops`, `model_schedule`, `route_errors`, `audit_routes`)
- `governance_domain/eval_runner.py` 801→173 (`eval_case_ops`, `eval_flow_ops`, `eval_run_ops`)
- `operations_core/freshness_store.py` 745→62 (`freshness_store_writes/queries`, `freshness_firestore_ops`)
- `budget_domain/service.py` 736→264 (`policy_ops`, `alert_ops`, `delivery_ops`, `ops_common`)
- `evaluation_domain/service.py` 813→275 (`case_ops`, `revision_ops`, `set_ops`)
- `workflow_handoff_nodes.py` 781→15 (`workflow_handoff_common/case/ticket/route_ops`)
- `quality_domain/service.py` 713→245 (`candidate_ops`, `case_lifecycle_ops`, `cluster_ops`)
- `evaluation_domain/job_repository.py` 698→191 (`job_lease_ops`, file/firestore adapters)
- `evaluation_domain/tool_fixtures.py` 691→265 (`tool_fixture_repository/sandbox/seeds`)
