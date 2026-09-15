# AI Ops Workflow Console Route Ledger

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
| `knowledge_ops` | `workHub` | `work`, `my-work`, `workHub` | `/console-v2/work` | *(authenticated actor)* | **v2** (W1 Spike) | **Live Only**. Legacy `vpnStory.js` mock isolated to legacy demo mode. | `/#knowledge_ops/workHub` |
| `knowledge_ops` | `quality` | `cases`, `improve`, `improve-cases` | `/console-v2/improvements/cases` | `ops.feedback.read` | **v2** (W2 Closed Loop) | **Live Only**. List route registered in `App.tsx` (`CasesListPage`) and backed by `/api/quality-cases`. | `/#knowledge_ops/quality` |
| `knowledge_ops` | `quality/:id` | `cases/:id`, `improve/:id` | `/console-v2/improvements/cases/:id` | `ops.feedback.read` | **v2** (W2 Closed Loop) | **Live Only**. Backed by `/api/quality-cases/{id}` and `/api/console/workflows/quality_case/{id}`. | `/#knowledge_ops/quality` |
| `knowledge_ops` | `contentHub` | `content`, `content-lists`, `docs` | `/console-v2/knowledge/documents` | `content.hub`, `knowledge.ui` | legacy (W3 target) | Live. Managed in Knowledge Portal bridge. | `/#knowledge_ops/contentHub` |
| `knowledge_ops` | `knowledgeWork` | - | `/console-v2/knowledge/work` | `knowledge.ui` | legacy (W3 target) | Live Knowledge Portal worklist. | `/#knowledge_ops/knowledgeWork` |
| `knowledge_ops` | `knowledgePortal` | - | `/console-v2/knowledge/documents` | `knowledge.ui` | legacy (W3 target) | Live Knowledge Portal document repo. | `/#knowledge_ops/knowledgePortal` |
| `knowledge_ops` | `faq` | - | `/console-v2/knowledge/faq` | `ops.faq.read` | legacy (W3 target) | Live Backoffice FAQ Domain. | `/#knowledge_ops/faq` |
| `knowledge_ops` | `knowledgeReviews` | - | `/console-v2/knowledge/reviews` | `knowledge.review.ui` | legacy (W3 target) | Live review queue from Knowledge Bridge. | `/#knowledge_ops/knowledgeReviews` |
| `knowledge_ops` | `knowledgeReleases`| - | `/console-v2/knowledge/releases` | `knowledge.ui` | legacy (W3 target) | Live release manifest log. | `/#knowledge_ops/knowledgeReleases` |
| `knowledge_ops` | `knowledge` | `content-performance`, `performance` | `/console-v2/knowledge/analytics` | `ops.knowledge.read` | legacy (W3 target) | Live retrieval & satisfaction metrics. | `/#knowledge_ops/knowledge` |
| `knowledge_ops` | `sync` | - | `/console-v2/knowledge/sync` | `ops.sync.read` | legacy (W3 target) | Live background connector sync jobs. | `/#knowledge_ops/sync` |
| `knowledge_ops` | `knowledgeAudit` | - | `/console-v2/knowledge/audit` | `knowledge.ui` | legacy (W5 target) | Live Knowledge audit trails. | `/#knowledge_ops/knowledgeAudit` |
| `knowledge_ops` / `ai_ops` | `evaluations` | `evaluations`, `golden` | `/console-v2/ai/evaluations` | `ops.evals.read` | legacy (W4 target) | Live evaluation suites and Golden sets. | `/#ai_ops/evaluations` |
| `knowledge_ops` / `ai_ops` | `examples` | - | `/console-v2/ai/examples` | `ops.examples.read` | legacy (W4 target) | Live few-shot classification examples. | `/#ai_ops/examples` |
| `knowledge_ops` | `conversations` | `conversations`, `chat` | `/console-v2/operations/conversations` | `ops.conversations.read` | legacy (W5 target) | Live masked user chat transcripts. | `/#knowledge_ops/conversations` |
| `ai_ops` | `prompts` | - | `/console-v2/ai/prompts` | `ops.prompts.read` | legacy (W4 target) | Live prompt candidates & version registry. | `/#ai_ops/prompts` |
| `ai_ops` | `models` | - | `/console-v2/ai/models` | `ops.models.read` | legacy (W4 target) | Live model inventory & parameters. | `/#ai_ops/models` |
| `ai_ops` | `flags` | - | `/console-v2/ai/flags` | `ops.flags.read` | legacy (W4 target) | Live feature flags registry. | `/#ai_ops/flags` |
| `platform` | `overview` | `analytics`, `analysis` | `/console-v2/operations/overview` | `ops.summary.read` | legacy (W5 target) | Live operational overview aggregates. | `/#platform/overview` |
| `platform` | `issues` | - | `/console-v2/operations/issues` | `ops.issues.read` | legacy (W5 target) | Live categorized taxonomy metrics. | `/#platform/issues` |
| `platform` | `routes` | - | `/console-v2/operations/routes` | `ops.issues.read` | legacy (W5 target) | Live grounding & agent intent routes. | `/#platform/routes` |
| `platform` | `costs` | - | `/console-v2/operations/costs` | `ops.cost.read` | legacy (W5 target) | Live model token expenditure. | `/#platform/costs` |
| `platform` | `budgets` | - | `/console-v2/operations/budgets` | `ops.budget.read` | legacy (W5 target) | Live budget policies & active alerts. | `/#platform/budgets` |
| `platform` | `health` | - | `/console-v2/operations/health` | `ops.health.read` | **v2** (W1 Spike) | **Live Only**. Backed by `/api/operations/health`. | `/#platform/health` |
| `platform` | `roles` | - | `/console-v2/governance/roles` | `ops.roles.read` | legacy (W5 target) | Live actor capabilities & role matrices. | `/#platform/roles` |
| `platform` | `retention` | - | `/console-v2/governance/retention` | `ops.retention.read` | legacy (W5 target) | Live data retention configuration. | `/#platform/retention` |
| `platform` | `masking` | - | `/console-v2/governance/masking` | `ops.retention.read` | legacy (W5 target) | Live PII masking rule sets. | `/#platform/masking` |
| `platform` | `search` | - | `/console-v2/operations/search` | `ops.search.read` | legacy (W5 target) | Live backoffice cross-entity search. | `/#platform/search` |
| `platform` | `audit` | - | `/console-v2/governance/audit` | `ops.audit.read` | legacy (W5 target) | Live append-only audit event stream. | `/#platform/audit` |

---

## 3. Legacy Hash Compatibility and Redirect Policy

### 3.1 Hash Format Translation
Legacy hash URLs adhere to one of the following patterns:
1. `/#<workspace>/<viewId>` (e.g. `/#knowledge_ops/quality`, `/#platform/health`)
2. `/#<alias>` (e.g. `/#work`, `/#cases`, `/#golden`)
3. `/#<workspace>/<viewId>?<queryParams>` (e.g. `/#knowledge_ops/quality?case_id=qc-1001`)

### 3.2 Dual-Way Routing Matrix
- When `console_v2_enabled` is active:
  - Navigating to `/console-v2/work` loads the V2 Work Hub.
  - Navigating to legacy hash `/#knowledge_ops/workHub` or `/#work` triggers a browser client redirect to `/console-v2/work` preserving query params and filter state.
  - Navigating to legacy hash `/#knowledge_ops/quality?case_id=qc-1001` or `/#cases?id=qc-1001` redirects to `/console-v2/improvements/cases/qc-1001`.
  - Non-migrated views (e.g. `/#ai_ops/models`) continue to render in the legacy UI shell without interference.
- When `console_v2_enabled` is disabled (kill switch):
  - Any access to `/console-v2/*` is redirected by FastAPI to the legacy shell root `/`.
  - All hash routes remain in the legacy application shell.

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
