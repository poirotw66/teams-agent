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
| H Oversized domain convergence | Ongoing — ~13 oversized files remain (was ~36); continue workflow/query/eval residuals |

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
- `operations/emitter.py` 678→203 (`emitter_turn/feedback/results/replay/...`)
- `services/export_service.py` 659→457 (`export_job_runner`, `export_artifact_gc`)
- `evaluation_domain/run_service.py` 657→269 (`run_create/review/outbox_ops`)
- `teams_agent/viewer_sessions.py` 708→78 (`viewer_sessions_types/memory/file/gcs`)
- `workers.py` 654→80 (`workers_retention/sync/budget/loops/lifespan`)
- `services/source_trace.py` 653→153 (`release/locator/mapping/resolve/payload`)
- `CaseDetailPage.tsx` 780→97 (`useCaseDetail`, header/body/modals/timeline)
- `extractor.py` 699→425 (`extractor_invoke/fallback/normalize`)
- `version_service.py` 652→175 (`version_create/draft/revision/test_cases`)
- `query_health.py` 596→98 (`query_health_probes/telemetry/summary/window`)
- `prompts_mixin.py` 585→391 (`prompt_canary_ops`, `prompt_candidate_ops`)
- `export_job_store.py` 584→76 (`export_job_lease`, file/firestore adapters)
- `eval_flow.py` 578→140 (`eval_flow_scripted/agent/unavailable`)
- `workflow_issue_processing.py` 579→254 (`knowledge/ticket/retrieval_probe` ops)
