# Historical POC resource → Terraform mapping

Default POC project recorded in earlier handoff material: `itr-aimasteryhub-lab` · Region: `asia-east1`

> **Historical evidence only — not a current cloud validation.** This file records a prior import mapping and reported plan. This Phase 0 change did not call GCP, initialize a remote backend, refresh state, import resources, or run a live plan. Confirm every identifier and the reviewed Terraform-owned Cloud Run shape under an approved change before using any command below.

Use this checklist when importing the environment created by `deploy/deploy-gcp.sh`.

## Resource map

| Live resource | Terraform resource | Import ID |
|---|---|---|
| Enabled APIs | `google_project_service.required["…"]` | `{project}/{service}` e.g. `itr-aimasteryhub-lab/run.googleapis.com` |
| Artifact Registry `teams-agent` | `google_artifact_registry_repository.teams_agent` | `projects/itr-aimasteryhub-lab/locations/asia-east1/repositories/teams-agent` |
| SA `teams-rag-agent@…` | `google_service_account.agent` | `projects/itr-aimasteryhub-lab/serviceAccounts/teams-rag-agent@itr-aimasteryhub-lab.iam.gserviceaccount.com` |
| SA `teams-agent-adapter@…` | `google_service_account.adapter` | `projects/itr-aimasteryhub-lab/serviceAccounts/teams-agent-adapter@itr-aimasteryhub-lab.iam.gserviceaccount.com` |
| Project IAM datastore.user (Agent SA) | `google_project_iam_member.agent_firestore` | `{project} roles/datastore.user serviceAccount:teams-rag-agent@…` |
| Project IAM BigQuery job user (Agent SA) | `google_project_iam_member.agent_bigquery_job_user` | `{project} roles/bigquery.jobUser serviceAccount:teams-rag-agent@…` |
| Table IAM operational event writer (Agent SA) | `google_bigquery_table_iam_member.agent_operational_events_writer` | `{project}/{dataset}/{table} roles/bigquery.dataEditor serviceAccount:teams-rag-agent@…` |
| Project IAM BigQuery job user (Backoffice SA) | `google_project_iam_member.backoffice_bigquery_job_user` | `{project} roles/bigquery.jobUser serviceAccount:teams-ai-ops-backoffice@…` |
| Dataset IAM analytics reader (Backoffice SA) | `google_bigquery_dataset_iam_member.backoffice_ai_ops_reader` | `{project}/{dataset} roles/bigquery.dataViewer serviceAccount:teams-ai-ops-backoffice@…` |
| Secret `teams-agent-google-api-key` | `google_secret_manager_secret.google_api_key` | `projects/itr-aimasteryhub-lab/secrets/teams-agent-google-api-key` |
| Secret `teams-agent-bot-client-secret` | `google_secret_manager_secret.bot_client_secret` | `projects/itr-aimasteryhub-lab/secrets/teams-agent-bot-client-secret` |
| Secret `teams-agent-asset-signing-key` | `google_secret_manager_secret.asset_signing_key` | `projects/itr-aimasteryhub-lab/secrets/teams-agent-asset-signing-key` |
| Secret IAM bindings | `google_secret_manager_secret_iam_member.*` | `{project}/{secret} roles/secretmanager.secretAccessor serviceAccount:…` |
| Firestore `(default)` | `google_firestore_database.default` | `projects/itr-aimasteryhub-lab/databases/(default)` |
| TTL on `conversations.expiresAt` | `google_firestore_field.conversations_expires_at_ttl` | `projects/…/databases/(default)/collectionGroups/conversations/fields/expiresAt` |
| TTL on `conversations_keys.expiresAt` | `google_firestore_field.conversation_keys_expires_at_ttl` | `…/collectionGroups/conversations_keys/fields/expiresAt` |
| TTL on `messages.expiresAt` | `google_firestore_field.messages_expires_at_ttl` | `…/collectionGroups/messages/fields/expiresAt` |
| TTL on `handoffs.retentionExpiresAt` | `google_firestore_field.handoffs_retention_ttl` | `…/collectionGroups/handoffs/fields/retentionExpiresAt` |
| TTL on `handoffs_events.retentionExpiresAt` | `google_firestore_field.handoff_events_retention_ttl` | `…/collectionGroups/handoffs_events/fields/retentionExpiresAt` |
| AI Ops deduplication read model | `google_bigquery_table.operational_events_deduplicated` | `projects/{project}/datasets/{dataset}/tables/{view}` |
| Cloud Run `teams-rag-agent` | `google_cloud_run_v2_service.agent[0]` | `projects/itr-aimasteryhub-lab/locations/asia-east1/services/teams-rag-agent` |
| Cloud Run `teams-agent-adapter` | `google_cloud_run_v2_service.adapter[0]` | `projects/itr-aimasteryhub-lab/locations/asia-east1/services/teams-agent-adapter` |
| Adapter → Agent invoker | `google_cloud_run_v2_service_iam_member.adapter_invokes_agent[0]` | `{project}/{region}/{agent}/roles/run.invoker/serviceAccount:teams-agent-adapter@…` |
| Adapter public invoker | `google_cloud_run_v2_service_iam_member.adapter_public[0]` | `{project}/{region}/{adapter}/roles/run.invoker/allUsers` |

Replace project/region/names if your tfvars differ.

## Environment backends

| Environment template | Backend template |
|---|---|
| Dev | `../environments/dev/backend.hcl` |
| Test | `../environments/test/backend.hcl` |
| POC | `../environments/poc/backend.hcl` |
| Prod | `../environments/prod/backend.hcl` |

Do not share state between environments. See [../DEPLOYER_IAM.md](../DEPLOYER_IAM.md).

## Import script (run from `infra/terraform`)

Set `PROJECT`, `REGION`, then import in dependency order:

```bash
PROJECT=itr-aimasteryhub-lab
REGION=asia-east1

for api in run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com iamcredentials.googleapis.com firestore.googleapis.com; do
  terraform import "google_project_service.required[\"${api}\"]" "${PROJECT}/${api}"
done

terraform import google_artifact_registry_repository.teams_agent \
  "projects/${PROJECT}/locations/${REGION}/repositories/teams-agent"

terraform import google_service_account.agent \
  "projects/${PROJECT}/serviceAccounts/teams-rag-agent@${PROJECT}.iam.gserviceaccount.com"
terraform import google_service_account.adapter \
  "projects/${PROJECT}/serviceAccounts/teams-agent-adapter@${PROJECT}.iam.gserviceaccount.com"

terraform import google_project_iam_member.agent_firestore \
  "${PROJECT} roles/datastore.user serviceAccount:teams-rag-agent@${PROJECT}.iam.gserviceaccount.com"

terraform import google_secret_manager_secret.google_api_key "projects/${PROJECT}/secrets/teams-agent-google-api-key"
terraform import google_secret_manager_secret.bot_client_secret "projects/${PROJECT}/secrets/teams-agent-bot-client-secret"
terraform import google_secret_manager_secret.asset_signing_key "projects/${PROJECT}/secrets/teams-agent-asset-signing-key"

terraform import google_firestore_database.default "projects/${PROJECT}/databases/(default)"

DB="projects/${PROJECT}/databases/(default)/collectionGroups"
terraform import google_firestore_field.conversations_expires_at_ttl "${DB}/conversations/fields/expiresAt"
terraform import google_firestore_field.conversation_keys_expires_at_ttl "${DB}/conversations_keys/fields/expiresAt"
terraform import google_firestore_field.messages_expires_at_ttl "${DB}/messages/fields/expiresAt"
terraform import google_firestore_field.handoffs_retention_ttl "${DB}/handoffs/fields/retentionExpiresAt"
terraform import google_firestore_field.handoff_events_retention_ttl "${DB}/handoffs_events/fields/retentionExpiresAt"

terraform import google_cloud_run_v2_service.agent[0] \
  "projects/${PROJECT}/locations/${REGION}/services/teams-rag-agent"
terraform import google_cloud_run_v2_service.adapter[0] \
  "projects/${PROJECT}/locations/${REGION}/services/teams-agent-adapter"

terraform import 'google_cloud_run_v2_service_iam_member.adapter_invokes_agent[0]' \
  "projects/${PROJECT}/locations/${REGION}/services/teams-rag-agent roles/run.invoker serviceAccount:teams-agent-adapter@${PROJECT}.iam.gserviceaccount.com"
terraform import 'google_cloud_run_v2_service_iam_member.adapter_public[0]' \
  "projects/${PROJECT}/locations/${REGION}/services/teams-agent-adapter roles/run.invoker allUsers"
```

Import secret IAM members individually if plan still shows drift:

```bash
terraform import google_secret_manager_secret_iam_member.agent_google_api_key \
  "projects/${PROJECT}/secrets/teams-agent-google-api-key roles/secretmanager.secretAccessor serviceAccount:teams-rag-agent@${PROJECT}.iam.gserviceaccount.com"
# … adapter bindings likewise
```

## Audit commands (export live config)

```bash
PROJECT=itr-aimasteryhub-lab
REGION=asia-east1

gcloud services list --enabled --project="$PROJECT"
gcloud artifacts repositories describe teams-agent --location="$REGION" --project="$PROJECT"
gcloud iam service-accounts list --project="$PROJECT"
gcloud projects get-iam-policy "$PROJECT" --format=json
gcloud secrets list --project="$PROJECT"
gcloud run services describe teams-rag-agent --region="$REGION" --project="$PROJECT" --format=export
gcloud run services describe teams-agent-adapter --region="$REGION" --project="$PROJECT" --format=export
gcloud firestore databases describe --database="(default)" --project="$PROJECT"
gcloud firestore fields ttls list --database="(default)" --project="$PROJECT"
```

## Reconciliation checklist (requires approved live verification)

- [ ] `environment_name` is one of `dev`, `test`, `poc`, `prod` and matches the isolated project/backend selected
- [ ] `adapter_public_base_url` in tfvars matches live Adapter URL
- [ ] `knowledge_portal_public_url` is a real Portal URL or deliberately empty (never the Adapter URL)
- [ ] `backoffice_auth_mode` matches live (`HEADER` for LAB import, `ENTRA` for production)
- [ ] `bot_client_id` / `bot_tenant_id` match `.env` (non-secret)
- [ ] Model env vars match approved deployment configuration
- [ ] All import commands succeeded
- [ ] Live Cloud Run templates match reviewed Terraform shape except image; Terraform must no longer ignore template/scaling drift
- [ ] The scoped BigQuery IAM and full event schema/view are reconciled without retaining project-wide Backoffice `dataEditor`
- [ ] An approved, credentialed plan has been reviewed; no zero-diff result is claimed from this document
- [ ] Secret **versions** exist (Terraform only manages containers)
- [ ] Knowledge bundle documented for image build

### Cloud Run template ownership

Terraform ignores only `template.containers[0].image` for release ownership. All other template fields, including runtime environment, scaling, service account, resources and secret references, are Terraform-owned and must be reconciled before an import is considered managed.

## Cloud Run shape reference (from deploy-gcp.sh)

| | Agent | Adapter |
|---|---|---|
| Auth | Private (`--no-allow-unauthenticated`) | Public (`allUsers` invoker) |
| CPU / memory | 1 / 2Gi | 1 / 512Mi |
| Concurrency | 8 | 40 |
| Timeout | 90s | 90s |
| Min / max instances | 0 / 3 | 0 / 3 |
| Service account | `teams-rag-agent` | `teams-agent-adapter` |
