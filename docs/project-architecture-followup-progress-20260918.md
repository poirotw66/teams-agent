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
| H Oversized domain convergence | Ongoing — FAQ service, source_routes, eval/quality/gate repos already shrunk; more remain |

## Recent Phase H wins
- `faq_domain/service.py` 865→436 (`transitions`, `lifecycle_ops`)
- `teams_agent/source_routes.py` 916→255 (`source_route_auth/payloads/streaming`)
- `teams_agent/source_links.py` 866→354 (`source_link_signing`, `source_link_access`)
- `evaluation_domain/gate_service.py` 821→457 (`gate_policy_ops`, `gate_release_ops`, `gate_case_ops`)
