# AI Ops Workflow Console Route Ledger

**Status (2026-09-18):** Migration complete for the product path. All 30 ledger-owned
routes are owned by React `/console-v2`. Default `/` and `/legacy` redirect to
`/console-v2/dashboard`; the legacy static family is emergency-only
(`BACKOFFICE_LEGACY_SHELL_ENABLED=true`).

## 1. Overview and Migration Principles

This Route Ledger tabulates all legacy navigation views, aliases, workspaces, and canonical `/console-v2/*` routes for the AI Ops Workflow Console.

### Core Architectural Rules
1. **Single Source of Truth**: At any milestone, each feature has exactly one canonical owner (`legacy` or `v2`). Legacy views and V2 views query the same underlying domain APIs (`/api/quality-cases`, `/api/faq`, `/api/evaluation`, etc.).
2. **Demo Isolation**: Legacy demo stories (such as `vpnStory.js` in `workHub.js`) must never be mixed into real queues, metrics, or telemetry. All `/console-v2/*` queues operate strictly on authenticated, server-authoritative live data.
3. **Safe Navigation and ReturnTo**: The `returnTo` parameter must be strictly validated against safe same-origin routes within the allowlist (`/`, `/#...`, `/console-v2/...`). External URLs, `javascript:` pseudoprotocols, and recursive `returnTo` sequences are rejected.
4. **Fail-Closed Access Control**: Client routes enforce capability requirements mapped to server-evaluated permissions. If a capability check fails, the UI redirects to a safe fallback or displays an unauthorized state without exposing internal metadata.

---

## 2. Route Ledger Table

| Legacy Workspace | Legacy View ID | Registered Aliases | Canonical Route (`/console-v2/`) | Capability Required | Current Owner (W0–W2) | Demo Isolation Status | Fallback / Handoff Target |
|---|---|---|---|---|---|---|---|
| `knowledge_ops` | `workHub` | `work`, `my-work`, `workHub` | `/console-v2/dashboard` (alias `/work` → dashboard) | *(authenticated actor)* | **v2** (W3 Workbench) | **Live Only**. Dashboard owns the former Work Hub landing. | `/#knowledge_ops/workHub` |
| `knowledge_ops` | `quality` | `cases`, `improve`, `improve-cases` | `/console-v2/triage` (alias `/improvements/cases` → triage) | `ops.feedback.read` | **v2** (W3 Triage) | **Live Only**. Quality case list flows through Triage queues. | `/#knowledge_ops/quality` |
| `knowledge_ops` | `quality/:id` | `cases/:id`, `improve/:id` | `/console-v2/improvements/cases/:id` | `ops.feedback.read` | **v2** (W2 Closed Loop) | **Live Only**. Backed by `/api/quality-cases/{id}` and `/api/console/workflows/quality_case/{id}`. | `/#knowledge_ops/quality` |
| `knowledge_ops` | `contentHub` | `content`, `content-lists`, `docs` | `/console-v2/knowledge` (docs tab) | `content.hub`, `knowledge.ui` | **v2** (W3 Knowledge) | **Live Only**. `KnowledgePage` Manual Docs tab. | `/#knowledge_ops/contentHub` |
| `knowledge_ops` | `knowledgeWork` | - | `/console-v2/knowledge` | `knowledge.ui` | **v2** (W3 Knowledge) | **Live Only**. Knowledge worklist absorbed into KnowledgePage. | `/#knowledge_ops/knowledgeWork` |
| `knowledge_ops` | `knowledgePortal` | - | `/console-v2/knowledge` | `knowledge.ui` | **v2** (W3 Knowledge) | **Live Only**. Document repo via Knowledge bridge + ManualDocsManager. | `/#knowledge_ops/knowledgePortal` |
| `knowledge_ops` | `faq` | - | `/console-v2/knowledge` (faqs tab) | `ops.faq.read` | **v2** (W3 Knowledge) | **Live Only**. `FaqManager` on KnowledgePage. | `/#knowledge_ops/faq` |
| `knowledge_ops` | `knowledgeReviews` | - | `/console-v2/knowledge/reviews` | `knowledge.review.ui` | **v2** (W4 Knowledge) | **Live Only**. `ReviewsPage` lists pending reviews. | `/#knowledge_ops/knowledgeReviews` |
| `knowledge_ops` | `knowledgeReleases`| - | `/console-v2/knowledge/releases` | `knowledge.ui` | **v2** (W4 Knowledge) | **Live Only**. `ReleasesPage` lists `/api/knowledge/releases`. | `/#knowledge_ops/knowledgeReleases` |
| `knowledge_ops` | `knowledge` | `content-performance`, `performance` | `/console-v2/knowledge/analytics` | `ops.knowledge.read` | **v2** (W4 Analytics) | **Live Only**. `KnowledgeAnalyticsPage` summary. | `/#knowledge_ops/knowledge` |
| `knowledge_ops` | `sync` | - | `/console-v2/knowledge/sync` | `ops.sync.read` | **v2** (W4 Sync) | **Live Only**. `SyncJobsPage` lists `/api/sync-jobs`. | `/#knowledge_ops/sync` |
| `knowledge_ops` | `knowledgeAudit` | - | `/console-v2/knowledge/audit` | `knowledge.ui` | **v2** (W4 Knowledge) | **Live Only**. `KnowledgeAuditPage` lists audit events. | `/#knowledge_ops/knowledgeAudit` |
| `knowledge_ops` / `ai_ops` | `evaluations` | `evaluations`, `golden` | `/console-v2/ai/evaluations` | `ops.evals.read` | **v2** (W4 Evaluations) | **Live Only**. `EvaluationsPage` lists `/api/evaluations/runs`. | `/#ai_ops/evaluations` |
| `knowledge_ops` / `ai_ops` | `examples` | - | `/console-v2/ai/examples` | `ops.examples.read` | **v2** (W4 AI) | **Live Only**. `ExamplesPage` lists `/api/examples`. | `/#ai_ops/examples` |
| `knowledge_ops` | `conversations` | `conversations`, `chat` | `/console-v2/triage` | `ops.conversations.read` | **v2** (W3 Triage) | **Live Only**. `TriagePage` + ConversationStream. | `/#knowledge_ops/conversations` |
| `ai_ops` | `prompts` | - | `/console-v2/ai/prompts` | `ops.prompts.read` | **v2** (W4 AI) | **Live Only**. `PromptsPage` lists `/api/prompts/candidates`. | `/#ai_ops/prompts` |
| `ai_ops` | `models` | - | `/console-v2/ai/models` | `ops.models.read` | **v2** (W4 AI) | **Live Only**. `ModelsPage` lists `/api/governance/models`. | `/#ai_ops/models` |
| `ai_ops` | `flags` | - | `/console-v2/ai/flags` | `ops.flags.read` | **v2** (W4 AI) | **Live Only**. `FlagsPage` lists `/api/governance/flags`. | `/#ai_ops/flags` |
| `platform` | `overview` | `analytics`, `analysis` | `/console-v2/dashboard` | `ops.summary.read` | **v2** (W3 Dashboard) | **Live Only**. Operational overview on DashboardPage. | `/#platform/overview` |
| `platform` | `issues` | - | `/console-v2/operations/issues` | `ops.issues.read` | **v2** (W4 Ops) | **Live Only**. `IssuesPage` summary. | `/#platform/issues` |
| `platform` | `routes` | - | `/console-v2/operations/routes` | `ops.issues.read` | **v2** (W4 Ops) | **Live Only**. `RoutesPage` summary. | `/#platform/routes` |
| `platform` | `costs` | - | `/console-v2/operations/costs` | `ops.cost.read` | **v2** (W4 Ops) | **Live Only**. `CostsPage` summary. | `/#platform/costs` |
| `platform` | `budgets` | - | `/console-v2/operations/budgets` | `ops.budget.read` | **v2** (W4 Ops) | **Live Only**. `BudgetsPage` lists `/api/budget-policies`. | `/#platform/budgets` |
| `platform` | `health` | - | `/console-v2/operations/health` | `ops.health.read` | **v2** (W1 Spike) | **Live Only**. Backed by `/api/operations/health`. | `/#platform/health` |
| `platform` | `roles` | - | `/console-v2/governance/roles` | `ops.roles.read` | **v2** (W4 Governance) | **Live Only**. `RolesPage` lists `/api/governance/roles`. | `/#platform/roles` |
| `platform` | `retention` | - | `/console-v2/governance/retention` | `ops.retention.read` | **v2** (W4 Governance) | **Live Only**. `RetentionPage`. | `/#platform/retention` |
| `platform` | `masking` | - | `/console-v2/governance/masking` | `ops.retention.read` | **v2** (W4 Governance) | **Live Only**. `MaskingPage`. | `/#platform/masking` |
| `platform` | `search` | - | `/console-v2/operations/search` | `ops.search.read` | **v2** (W4 Ops) | **Live Only**. `SearchPage` queries `/api/governance/search`. | `/#platform/search` |
| `platform` | `audit` | - | `/console-v2/governance/audit` | `ops.audit.read` | **v2** (W4 Governance) | **Live Only**. `AuditPage` lists `/api/governance/audit`. | `/#platform/audit` |
| — | `tickets` (new) | — | `/console-v2/tickets` | `ops.conversations.read` | **v2** (W3 Tickets) | **Live Only**. TicketsPage for IT ticket tracking. | `/console-v2/tickets` |

---

## 3. Legacy Hash Compatibility and Redirect Policy

### 3.1 Hash Format Translation
Legacy hash URLs adhere to one of the following patterns:
1. `/#<workspace>/<viewId>` (e.g. `/#knowledge_ops/quality`, `/#platform/health`)
2. `/#<alias>` (e.g. `/#work`, `/#cases`, `/#golden`)
3. `/#<workspace>/<viewId>?<queryParams>` (e.g. `/#knowledge_ops/quality?case_id=qc-1001`)

### 3.2 Dual-Way Routing Matrix
- When `console_v2_enabled` is active (default):
  - `GET /` redirects to `/console-v2/dashboard` (legacy shell is not the normal product path).
  - `GET /legacy` also redirects to `/console-v2/dashboard` unless `BACKOFFICE_LEGACY_SHELL_ENABLED=true`.
  - The classic SPA bundle lives under `/static/legacy-js/` (not `/static/js/`). Product path never loads that full bundle; `/static/js/main.js` is only a thin redirect stub to `/console-v2/dashboard`.
  - When `BACKOFFICE_LEGACY_SHELL_ENABLED=true`, `/legacy` serves `static/legacy-js/index.html` with import map + entry from `/static/legacy-js/`.
  - Navigating to `/console-v2/*` loads the React Console for all ledger-owned routes (30/30 v2).
  - Navigating to legacy hash `/#knowledge_ops/workHub` or `/#work` triggers a browser client redirect to `/console-v2/work` preserving query params and filter state.
  - Navigating to legacy hash `/#knowledge_ops/quality?case_id=qc-1001` or `/#cases?id=qc-1001` redirects to `/console-v2/improvements/cases/qc-1001`.
- When `console_v2_enabled` is disabled (kill switch):
  - Any access to `/console-v2/*` is redirected by FastAPI to the legacy shell root `/`.
  - `GET /` serves the legacy application shell from `/static/legacy-js/`; all hash routes remain there.

---

## 4. Work Queue Aggregation Contract

### 4.1 Buckets
The Work Hub aggregates actionable work into 4 canonical buckets:
1. `pending_action` (待處理):
   - Quality cases in `NEW`, `TRIAGED`, or `IN_PROGRESS` assigned to current actor or team.
2. `pending_review` (待審核):
   - Quality cases in `WAITING_REVIEW`.
   - Knowledge document drafts awaiting editorial or peer review.
   - AI Governance gate decisions awaiting evaluation sign-off.
3. `tracking` (觀察中):
   - Quality cases in `OBSERVING` with ongoing metric monitoring.
4. `completed` (已結案):
   - Quality cases in `RESOLVED`, `WONT_FIX`, or `DUPLICATE`.

### 4.2 Security and Tenant Boundaries
- Aggregated endpoints strictly filter by the authenticated `ActorContext`.
- Unassigned items in `pending_action` are only visible to actors possessing the corresponding unit or role capability (e.g. `ops.feedback.write`).
- Cursor tokens are encrypted or opaque base64-encoded hashes bound to `(actor_id, tenant_id, bucket, timestamp)`. Replaying cursors across actors is strictly rejected.
