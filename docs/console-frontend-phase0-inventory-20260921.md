# Console Frontend Phase 0 Inventory

> Date: 2026-09-21  
> Spec: `docs/console-frontend-architecture-optimization-spec-20260921.md`  
> Status: Phase 0 deliverable from current source (not a claim that Phases 1–4 are done)

## 1. Route / navigation / owner map

Basename: `/console-v2`. Nav is Header-only (no sidebar).

| Path | Kind | Page owner | Header nav | Active-key behavior |
|---|---|---|---|---|
| `/login` | page | auth | no | — |
| `/` | redirect → `/dashboard` | — | — | — |
| `/dashboard` | page | dashboard | yes | selected |
| `/work` | alias → `/dashboard` | — | — | dashboard |
| `/triage` | page | triage | yes | selected |
| `/improvements` | alias → `/triage` | — | — | triage |
| `/improvements/cases` | alias → `/triage` | — | — | triage |
| `/improvements/cases/:id` | page | improvements | no | falls back to dashboard |
| `/knowledge` | page | knowledge | yes | selected |
| `/knowledge/reviews` | page | knowledge | no | knowledge parent |
| `/knowledge/releases` | page | knowledge | no | knowledge parent |
| `/knowledge/sync` | page | knowledge | no | knowledge parent |
| `/knowledge/analytics` | page | operations | no | knowledge parent |
| `/knowledge/audit` | page | operations | no | knowledge parent |
| `/tickets` | page | tickets | yes | selected |
| `/operations/health` | page | operations | yes | selected only this path |
| `/operations/issues` | page | operations | no | falls back to dashboard |
| `/operations/routes` | page | operations | no | falls back to dashboard |
| `/operations/costs` | page | operations | no | falls back to dashboard |
| `/operations/budgets` | page | operations | no | falls back to dashboard |
| `/operations/search` | page | operations | no | falls back to dashboard |
| `/ai/evaluations` | page | evaluations | no | falls back to dashboard |
| `/ai/evals` | alias → `/ai/evaluations` | — | — | falls back to dashboard |
| `/ai/examples` | page | ai | no | falls back to dashboard |
| `/ai/prompts` | page | ai | no | falls back to dashboard |
| `/ai/models` | page | governance | no | falls back to dashboard |
| `/ai/flags` | page | governance | no | falls back to dashboard |
| `/governance/roles` | page | governance | no | falls back to dashboard |
| `/governance/retention` | page | governance | no | falls back to dashboard |
| `/governance/masking` | page | governance | no | falls back to dashboard |
| `/governance/audit` | page | governance | no | falls back to dashboard |

Unwired page modules (exist, not in `App.tsx`): `CasesListPage.tsx`, `WorkPage.tsx`.

## 2. P0 mutation contracts (as found)

| Operation | UI entry | API | Pre-fix behavior | Gap |
|---|---|---|---|---|
| FAQ save | `QuickFaqDrawer` | `POST /api/console/workbench/faqs` | UI did not await; success + close before confirm; copy claimed vector/Teams sync | await + honest copy |
| Broadcast | `BroadcastModal` | `POST /api/console/workbench/broadcast` | UI did not await; success + close before confirm | await; show server `expires_at` |
| Root cause | `TriageActionPanel` | `POST .../conversations/{id}/action` | optimistic local update; API errors swallowed | confirm-then-update; surface errors |
| Resolve | `TriageActionPanel`, `ActionInbox` | same action API | same as root cause | shared await path |
| Escalate ticket | `EscalateTicketModal` | ticket create | awaits (good); API errors silent | visible API error |
| Golden Eval | `TriageActionPanel` | none wired | fake success toast only | wire `POST /api/evaluations/cases` |

## 3. Golden Eval API availability

**Available.** Backend `POST /api/evaluations/cases` (`ops.evals.write`) accepts `source_type: "CONVERSATION"` and `source_id`. Generated client: `backofficeClient.create_case_api_evaluations_cases_post`.

Gap was frontend-only: Triage button never called the API. Phase 1 wires create-case; does not auto-publish into an eval set (that remains a separate review/set workflow).

## 4. Capability surface (for Phase 2 registry)

- Frontend `/api/capabilities` consumers: `authProvider`, `LoginPage`.
- `accessControlProvider`: unknown resources default `can: true` (fail-open) — Phase 2 must fail closed.
- `authProvider.onError`: 401 and 403 both force logout — Phase 2 must separate them.
- `session.ts`: without bearer, defaults to `SYSTEM_ADMIN` header auth — production deploy check (`authMode=ENTRA`) remains required; not claimed as an active production bypass.
- Backend capability universe: `operations_core/access.py` (`ops.*`) plus knowledge-bridge keys (`knowledge.*`).

Capability keys to map in Phase 2 (non-exhaustive seeds):  
`ops.health.read`, `ops.config.read`, `ops.summary.read`, `ops.conversations.read`, `ops.knowledge.read`, `ops.faq.{read,write}`, `ops.quality.{read,write,resolve}`, `ops.evals.{read,write,review,sets.publish,run,export}`, `ops.cost.{read,write}`, `ops.budget.{read,write}`, `ops.search.read`, `ops.roles.read`, `ops.retention.{read,write}`, `ops.audit.read`, `ops.prompts.*`, `ops.models.*`, `ops.flags.*`, plus knowledge-bridge create/edit/review/publish keys.

## 5. Workbench `loadAll` domains

Triggered on first store subscribe: overview, conversations, FAQs, documents, tickets.  
Subscribers: Dashboard, Triage, Knowledge, Tickets (+ error banner). Phase 3 migrates to per-page loads.

## 6. Baseline gaps (explicit unknowns)

1. Production always-Entra vs header-auth inertness — deploy verification, not proven from FE alone.
2. Preferred post-create Golden Eval UX (stay on triage vs deep-link to `/ai/evaluations` case detail) — product decision after create works.
3. Browser screenshots / network baseline for perf — deferred to Phase 4 measurement pass.
4. Role matrix fixtures against live `/api/capabilities` — Phase 2 deliverable.

## 7. Existing automated coverage relevant to this program

Present: route structure smoke (`tests/app_routes.test.mjs`), workbench load surfaces, session header tests, a few triage/markdown component tests.  
Missing before Phase 1: FAQ/broadcast/resolve/root-cause/escalate failure UX, Golden Eval write, accessControl fail-closed, 401 vs 403.

## 8. Implementation progress (working tree, 2026-09-21)

Verified locally:

- `npm test --prefix console_frontend` — 53 passed (includes role matrix, health badge, mutation feedback)
- `console_frontend/node_modules/.bin/tsc --noEmit -p console_frontend` — clean
- `PYTHONPATH=agent_service/src uv run python scripts/sync_console_v2.py --check` — committed assets match rebuild
- `CONSOLE_E2E_BASE_URL=http://127.0.0.1:8092 node --test console_frontend/tests/console_e2e_smoke.test.mjs` — live health/shell/capabilities/FAQ write smoke passed
- Browser open of `/console-v2/dashboard` shows registry-driven nav, FAQ gated button, Action Inbox (no hard-coded green health tags)

Section 11 closed — see `docs/console-frontend-phase4-acceptance-20260921.md`:

- Interactive browser E2E: dashboard → triage → FAQ save (POST 200 + list readback); VIEWER 403 stay-authed
- Viewport / keyboard matrix at 360 / 768 / 1024 / 1440 + 200% zoom (no FAQ∩triage overlap; no fixed 760px)
- Perf after-baseline: `data/eval/reports/console-frontend-perf-baseline-20260921.json`
- Production ENTRA / header-auth denial: `console_release_gates.test.mjs` + live `/api/auth/config`
