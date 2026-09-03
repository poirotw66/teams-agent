# AI Ops infrastructure review — Phase 0 baseline

## Scope and assurance boundary

This review implements the Terraform portion of the Phase 0 foundation specification. It establishes environment naming, state/data-isolation templates, retention defaults, analytics storage shape, least-privilege BigQuery access, and Cloud Run ownership boundaries.

It does **not** claim a cloud deployment, import, refresh, state migration, live plan, or smoke test. No environment project ID was invented for dev, test, or prod. Their files are intentionally templates. The LAB record in `infra/ai-ops-environment-inventory.json` and `infra/terraform/INVENTORY.md` is labelled historical, including its 2026-09-02 reported zero-plan result.

## Implemented contract

| Phase 0 requirement | Terraform baseline |
|---|---|
| dev/test/poc/prod isolation | `environment_name` permits only those four values and is independent of `deployment_phase`; separate dev/test/poc/prod backend templates use distinct state prefixes. The operating procedure requires a distinct GCP project for each environment. |
| Runtime environment attribution | Agent, Adapter, and Backoffice all receive `AGENT_DEPLOYMENT_ENV = var.environment_name`. `prepare`, `activate`, and `full` are never emitted as an analytics environment. |
| One-year detail retention | Conversation and handoff runtime defaults are 365 days; Firestore TTL policies cover the corresponding expiration fields. BigQuery event partitions expire after 365 days. A non-production TTL test may set a shorter value. |
| Event envelope and idempotency | `operational_events` includes event/schema/ingest time, environment, tenant/team/channel, conversation/turn/request/correlation, issue/taxonomy, pseudonymous actor, classification/masking/retention, and JSON payload fields. The deduplicated view selects the latest `ingested_at` row per immutable `event_id`. |
| Queryable analytics performance | The table requires a time partition filter and clusters environment, tenant, event type, and correlation ID. |
| BigQuery least privilege | Agent: project `bigquery.jobUser` plus table-only `dataEditor` for event ingestion. Backoffice: project `bigquery.jobUser` plus `dataViewer` on the AI Ops dataset. The former project-wide Backoffice `dataEditor` grant is removed. |
| Real Portal link boundary | `knowledge_portal_public_url` is a separately configured HTTPS URL. It is not derived from `adapter_public_base_url`; absent configuration is sent as an empty URL plus `KNOWLEDGE_PORTAL_URL_CONFIGURED=false`. |
| Terraform ownership / drift | Cloud Run ignores only container image updates. Template environment, scaling, resources, service account and secret references are Terraform-owned and must reconcile in an approved plan. |

## Runtime handoff interface — intentionally not deployed here

The event outbox and delivery worker belong to the application/runtime subtask. Terraform does not invent a queue, topic, scheduler, or deployment for an interface that has not been agreed by that owner.

Before enabling BigQuery event delivery, the runtime owner must provide a versioned interface that guarantees:

- an immutable `event_id` reused on retry;
- the Phase 0 envelope fields represented by the table schema, including `environment`, tenant scope, conversation/turn/request IDs, `correlation_id`, and `retention_expires_at`;
- masked, non-credential payloads and pseudonymous `actor_ref` only;
- at-least-once delivery that is safe with the deduplication view, plus a documented late-event ordering policy; and
- an explicit failure/observability path that does not add more than the specified synchronous turn latency.

The Backoffice must treat `KNOWLEDGE_PORTAL_URL_CONFIGURED=false` as an unconfigured integration, not silently navigate to the Teams Adapter. Capability/data-scope enforcement, unmasked-read justification, Audit append/fail-closed behavior, masking, and legal-hold decisions remain runtime/governance work; Terraform cannot certify them.

## Required authorized follow-up

1. Choose isolated dev, test, poc, and prod projects/state buckets; replace only the template placeholders in the selected environment.
2. Under an approved change, inspect existing POC Cloud Run template, BigQuery IAM/schema, Firestore TTL field policies, and any existing datasets before importing or applying.
3. Run an authorized refresh-backed plan and review Cloud Run shape reconciliation, IAM replacement, dataset/table/view creation or import, and the retention migration impact.
4. In test, inject documents with shortened expiry fields and verify actual Firestore TTL deletion; verify one-year event partition expiry and the event-id deduplication query against replayed masked test events.
5. Obtain security/legal approval for transcript deletion, aggregate retention, legal hold, Entra role mapping, and any unmasked/export capability before production activation.

These steps are deliberately not performed by this change.
