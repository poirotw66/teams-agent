# Live resource → Terraform mapping

Default POC project: `itr-aimasteryhub-lab` · Region: `asia-east1`

Use this checklist when importing the environment created by `deploy/deploy-gcp.sh`.

## Resource map

| Live resource | Terraform resource | Import ID |
|---|---|---|
| Enabled APIs | `google_project_service.required["…"]` | `{project}/{service}` e.g. `itr-aimasteryhub-lab/run.googleapis.com` |
| Artifact Registry `teams-agent` | `google_artifact_registry_repository.teams_agent` | `projects/itr-aimasteryhub-lab/locations/asia-east1/repositories/teams-agent` |
| SA `teams-rag-agent@…` | `google_service_account.agent` | `projects/itr-aimasteryhub-lab/serviceAccounts/teams-rag-agent@itr-aimasteryhub-lab.iam.gserviceaccount.com` |
| SA `teams-agent-adapter@…` | `google_service_account.adapter` | `projects/itr-aimasteryhub-lab/serviceAccounts/teams-agent-adapter@itr-aimasteryhub-lab.iam.gserviceaccount.com` |
| Project IAM datastore.user (Agent SA) | `google_project_iam_member.agent_firestore` | `{project} roles/datastore.user serviceAccount:teams-rag-agent@…` |
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
| Cloud Run `teams-rag-agent` | `google_cloud_run_v2_service.agent` | `projects/itr-aimasteryhub-lab/locations/asia-east1/services/teams-rag-agent` |
| Cloud Run `teams-agent-adapter` | `google_cloud_run_v2_service.adapter` | `projects/itr-aimasteryhub-lab/locations/asia-east1/services/teams-agent-adapter` |
| Adapter → Agent invoker | `google_cloud_run_v2_service_iam_member.adapter_invokes_agent` | `{project}/{region}/{agent}/roles/run.invoker/serviceAccount:teams-agent-adapter@…` |
| Adapter public invoker | `google_cloud_run_v2_service_iam_member.adapter_public` | `{project}/{region}/{adapter}/roles/run.invoker/allUsers` |

Replace project/region/names if your tfvars differ.

## Environment backends

| Workflow | Init command |
|---|---|
| POC import | `terraform init -backend-config=../environments/poc/backend.hcl` |
| New test project | `terraform init -backend-config=../environments/test/backend.hcl` |

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

terraform import google_cloud_run_v2_service.agent \
  "projects/${PROJECT}/locations/${REGION}/services/teams-rag-agent"
terraform import google_cloud_run_v2_service.adapter \
  "projects/${PROJECT}/locations/${REGION}/services/teams-agent-adapter"

terraform import google_cloud_run_v2_service_iam_member.adapter_invokes_agent \
  "projects/${PROJECT}/locations/${REGION}/services/teams-rag-agent roles/run.invoker serviceAccount:teams-agent-adapter@${PROJECT}.iam.gserviceaccount.com"
terraform import google_cloud_run_v2_service_iam_member.adapter_public \
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

## Zero-diff checklist

- [ ] `adapter_public_base_url` in tfvars matches live Adapter URL
- [ ] `bot_client_id` / `bot_tenant_id` match `.env` (non-secret)
- [ ] Model env vars match `agent_service/.env`
- [ ] All import commands succeeded
- [ ] `terraform plan` shows **0 add, 0 change, 0 destroy**
- [ ] Secret **versions** exist (Terraform only manages containers)
- [ ] Knowledge bundle documented for image build

## Cloud Run shape reference (from deploy-gcp.sh)

| | Agent | Adapter |
|---|---|---|
| Auth | Private (`--no-allow-unauthenticated`) | Public (`allUsers` invoker) |
| CPU / memory | 1 / 2Gi | 1 / 512Mi |
| Concurrency | 8 | 40 |
| Timeout | 90s | 90s |
| Min / max instances | 0 / 3 | 0 / 3 |
| Service account | `teams-rag-agent` | `teams-agent-adapter` |
