# Architecture Convergence Progress (2026-09-19)

Tracks execution of [`docs/0919-arch.md`](./0919-arch.md).

## Status

| Priority | Item | Status |
|---|---|---|
| P0 | Protect `main` (required checks + PR-only) | **Done** — GitHub branch protection enabled |
| P0 | GCS Knowledge Release as sole SoT; fix deploy doc drift | **Done** — docs rewritten + `scripts/check_knowledge_image_sot.py` |
| P1 | uv workspace + runtime-scoped deps | **Mostly done** — workspace members + scoped Docker extras; cores already under `agent_service/src/{platform,operations,knowledge}_*`; full `packages/`/`apps/` move deferred |
| P1 | Turn Planner PoC (4-call → 2-call, Golden Eval) | **Done (flag off)** — `TurnPlanner` + `TURN_PLANNER_ENABLED`; A/B via `scripts/agent_turn_benchmark.py --mode compare`; keep off until Golden Eval wins |
| P1 | Trust / provenance boundary for retrieval vs display | **Done** — `Issue.retrieval_query` + `issue_trust`; knowledge search prefers retrieval query over display description |
| P2 | Extract citation/viewer from Teams Adapter | **Done (in-repo)** — `src/citation_asset_gateway/` + Adapter shims; public `/rag-*` paths unchanged |
| P2 | OpenTelemetry + SLO foundations | **Done (foundations)** — optional `[otel]` extra, `OTEL_*` settings, `agent.workflow.run` span, documented SLO targets |

## P0 evidence

- Branch protection on `main`: required status checks `teams-adapter`,
  `agent-service`, `playground`, `console-frontend`; require PR reviews (1);
  dismiss stale; enforce admins; no force push; conversation resolution required.
- Docs: `deploy/README.md`, `README.md`, `README-TW.md` describe GCS immutable
  releases as production SoT; removed “developer machine must hold corpus” path.
- Gate: `uv run python scripts/check_knowledge_image_sot.py` fails if
  `agent_service/Dockerfile` reintroduces corpus/index bake.

## P1 notes

- `agent_service/Dockerfile`: `--extra firestore` only (no `portal`, no `bigquery`).
- `agent_service/Dockerfile.backoffice`: `--extra firestore` only (no `portal`).
- `agent_service/Dockerfile.portal`: keeps `--extra firestore --extra portal`.
- Workspace: see `docs/uv-workspace-layout.md`.
- Turn Planner PoC (`agent_service/src/agent_service/turn_planner.py`):
  - Env: `TURN_PLANNER_ENABLED=true` replaces supervisor+extractor with one
    structured plan (route + issues + `retrievalIntent`).
  - Default remains supervisor-first until Golden Eval Accuracy / P95 / Cost
    review (docs/0919-arch.md).
  - Stub A/B: from `agent_service/`,
    `uv run python ../scripts/agent_turn_benchmark.py --mode compare`.
  - Live accuracy still uses `scripts/run_golden_baseline.py` against both
    configs before cutover.
  - Stub compare (2026-09-19): greetings/meta stay 0-LLM; IT knowledge/clarification
    still often +1 vs current baseline because supervisor already skips its
    model on standalone IT turns. Keep flag off until Golden Eval proves a win.

## P2 notes

- Citation Asset Gateway: implementation under `src/citation_asset_gateway/`;
  `teams_agent.source_*` / `media` / `viewer_sessions*` are thin re-export shims.
- OTel: `uv sync --extra otel` then `OTEL_ENABLED=true` (+ optional
  `OTEL_EXPORTER_OTLP_ENDPOINT`). SLO targets live in
  `agent_service.observability.SLO_TARGETS` for ops review, not auto-enforced.
