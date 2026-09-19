# Architecture Convergence Progress (2026-09-19)

Tracks execution of [`docs/0919-arch.md`](./0919-arch.md).

## Status

| Priority | Item | Status |
|---|---|---|
| P0 | Protect `main` (required checks + PR-only) | **Done** — GitHub branch protection enabled |
| P0 | GCS Knowledge Release as sole SoT; fix deploy doc drift | **Done** — docs rewritten + `scripts/check_knowledge_image_sot.py` |
| P1 | uv workspace + runtime-scoped deps | Pending |
| P1 | Turn Planner PoC (4-call → 2-call, Golden Eval) | Pending |
| P1 | Trust / provenance boundary for retrieval vs display | Pending |
| P2 | Extract citation/viewer from Teams Adapter | Pending |
| P2 | OpenTelemetry + SLO foundations | Pending |

## P0 evidence

- Branch protection on `main`: required status checks `teams-adapter`,
  `agent-service`, `playground`, `console-frontend`; require PR reviews (1);
  dismiss stale; enforce admins; no force push; conversation resolution required.
- Docs: `deploy/README.md`, `README.md`, `README-TW.md` describe GCS immutable
  releases as production SoT; removed “developer machine must hold corpus” path.
- Gate: `uv run python scripts/check_knowledge_image_sot.py` fails if
  `agent_service/Dockerfile` reintroduces corpus/index bake.
