# Console Frontend Phase 4 Acceptance Evidence — 2026-09-21

Evidence against `docs/console-frontend-architecture-optimization-spec-20260921.md` §11.
Authoritative sources: working tree, live backoffice at `http://127.0.0.1:8092`, automated tests, browser interactive pass.

## Gates run

| Gate | Result |
|---|---|
| `npm test --prefix console_frontend` | 53 passed / 17 files |
| `npx tsc --noEmit` (console_frontend) | clean |
| `PYTHONPATH=agent_service/src uv run python scripts/sync_console_v2.py --check` | committed bundle matches rebuild |
| `CONSOLE_E2E_BASE_URL=http://127.0.0.1:8092 node --test console_frontend/tests/*.test.mjs` | 11 passed (App wiring, live smoke, VIEWER 403, ENTRA release gates) |

## Interactive browser E2E

Base: `http://127.0.0.1:8092/console-v2/` (local HEADER auth / SYSTEM_ADMIN).

1. **Dashboard → Triage nav**: menuitem「對話與分診」navigates to `/console-v2/triage` without FAQ button intercept (two-row Header layout).
2. **Triage → FAQ drawer → save**:「修訂此知識 / FAQ」opens drawer; save awaits `POST /api/console/workbench/faqs` → **200** with body `id=faq-20260921072848` then success toast; drawer closes only after resolve.
3. **Narrow viewport save**: at Emulation width **360px**,「快速新增 FAQ」save → **200** `id=faq-20260921072958`; list readback confirms both E2E FAQs.
4. **403 path (automated live)**: VIEWER `POST /api/console/workbench/faqs` → 403; subsequent `/api/capabilities` still 200 with `role=VIEWER`; conversations read still 200.

## Viewport / a11y matrix

Measured in-page at widths **360 / 768 / 1024 / 1440** and **200% zoom**:

| Width | Primary nav present | FAQ button | FAQ∩Triage overlap | Fixed 760px nodes |
|---|---|---|---|---|
| 360 | yes (儀表板…更多功能) | yes | no | 0 |
| 768 | yes | yes | no | 0 |
| 1024 | yes | yes | no | 0 |
| 1440 | yes | yes | no | 0 |
| 200% zoom | triage + FAQ visible | yes | no | — |

Keyboard: first focusables include「返回營運儀表板」「快速新增 FAQ」「舊版後台」and the horizontal menu. Core triage queue remains usable at 360px (search + filter + list).

## Perf after-baseline

File: `data/eval/reports/console-frontend-perf-baseline-20260921.json`

| Metric | After (this branch) |
|---|---|
| Total asset bytes | 2,196,283 (~2.09 MiB) |
| Chunk count | 28 |
| `index-*.js` | 85,218 |
| `vendor-antd-*.js` | 700,859 |
| `DashboardPage-*.js` | 21,855 |
| `TriagePage-*.js` | 31,665 |

Pre-change totals were not captured on this branch before Phase 0; this JSON is the post-optimization baseline for future regressions. Lazy feature chunks remain split from vendors.

## Production ENTRA evidence (release gates)

From `console_frontend/tests/console_release_gates.test.mjs` (passed):

- `deploy/deploy-backoffice.sh` defaults `BACKOFFICE_AUTH_MODE` to **ENTRA** and wires Entra tenant/client IDs.
- `config_validator.py` requires ENTRA in production and blocks unsafe file stores.
- `auth.py` denies header auth outside `dev` / `test` / `poc`.
- Live `/api/auth/config` exposes `authMode` + `headerAuthAllowed` (local may allow header; production path is gated by validator + deploy default).

## §11 checklist

| # | Requirement | Evidence |
|---|---|---|
| 1 | Writes succeed only after backend confirm; no success toast / irreversible fake local state on error | QuickFaqDrawer / Broadcast / triage mutation tests; live FAQ POST 200 before toast |
| 2 | Golden Eval persists or is explicitly non-operable | `goldenEvalCases` POST + panel tests (403/5xx no success claim) |
| 3 | Capability registry fail-closed; 403 does not logout | `routeRegistry` fail-closed test; `authProvider` 401 vs 403; live VIEWER 403 |
| 4 | Per-page domain load; partial failure ≠ zero | `ensureDomains` + KpiCards error copy; domain load tests |
| 5 | Logout / identity change clears workbench; prod rejects self-asserted admin header | `clearIdentityBoundState` → `workbenchStore.resetForIdentityChange`; release gates |
| 6 | Nav coverage + active state; narrow / 200% / keyboard core tasks | Header registry nav; viewport matrix above; interactive triage→FAQ |
| 7 | Health from live summary, not static green | `ServiceHealthBadge` + `/api/health/summary` live |
| 8 | Tests, typecheck, sync check, perf record | Gates table + perf JSON |
