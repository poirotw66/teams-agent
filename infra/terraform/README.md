# Terraform — Teams Agent and AI Ops foundation

Minimal, readable IaC for the Teams Agent POC on GCP. This describes **long-lived infrastructure**; it does **not** store secret **values** or replace application release (image build/deploy).

## Two workflows — do not mix them

| Workflow | Backend | tfvars example | Image policy |
|---|---|---|---|
| **POC import** (existing `deploy-gcp.sh` project) | `../environments/poc/backend.hcl` | `../environments/poc/terraform.tfvars.example` | `environment_name = "poc"`, `deployment_phase = "full"` |
| **New dev/test project** | `../environments/dev/` or `../environments/test/` | matching `terraform.tfvars.example` | `environment_name = "dev"` or `"test"`; two-phase bootstrap |
| **Production template** | `../environments/prod/` | `../environments/prod/terraform.tfvars.example` | `environment_name = "prod"`, Entra, immutable images |

`environment_name` is a governed runtime/data value (`dev`, `test`, `poc`, `prod`), not a deployment workflow value. `deployment_phase` only controls the prepare/activate workflow. Each environment must use a different GCP project for production data isolation and a **different GCS state bucket or prefix**; never bootstrap an environment against the POC backend. The dev/test/prod files are templates, not declarations that projects or resources already exist.

Deployer / CI identities: [../DEPLOYER_IAM.md](../DEPLOYER_IAM.md).

## Deployment phases

Greenfield projects split Terraform into two applies so Artifact Registry and secret containers exist before images or Cloud Run:

| Phase | `deployment_phase` | Creates |
|---|---|---|
| **Prepare Environment** | `prepare` | APIs, Artifact Registry, service accounts, secret containers + IAM, Firestore, Agent Firestore IAM |
| **Activate Services** | `activate` | Cloud Run Agent + Adapter, Cloud Run IAM, runtime env, secret references |
| **POC import** | `full` | Everything at once (existing live stack); reconcile Terraform-owned shape before calling it managed |

Wrapper scripts (no manual `-target`):

- `../scripts/terraform-prepare.sh [backend.hcl]`
- `../scripts/terraform-activate.sh [backend.hcl]`

## Scope

| Managed by Terraform | Not managed by Terraform |
|---|---|
| Required GCP APIs | Secret **values** (API keys, client secrets) |
| Artifact Registry repository | Teams Developer Portal settings |
| Agent / Adapter service accounts | Knowledge bundle contents (`data/sources`, `data/index`) |
| IAM (Firestore, Secret Accessor, Run invoker, scoped BigQuery access) | Playground / Mock Ticket (optional UAT) |
| Secret Manager secret **containers** + IAM | Entra client secret value |
| Firestore database + TTL field policies | Production HA / VPC / WAF / DR |
| Cloud Run service **shape** (CPU, memory, env, SA, IAM) | Cloud Build job definitions (in `deploy/`) |
| AI Ops BigQuery dataset/table/view, one-year partition expiry | Application event delivery/outbox implementation |

## Ownership boundary

```text
terraform prepare  → foundation (no Cloud Run)
secret injection   → secret values
BUILD_ONLY release → push pinned images to Artifact Registry
terraform activate → Cloud Run shape + secret refs
release-gcp.sh     → subsequent immutable image updates only
smoke test         → /readyz, Agent IAM, Teams E2E
```

Terraform owns the Cloud Run service shape: service account, timeout, concurrency, scaling, resources, environment and secret references. Only the container **image** is ignored after creation, so the approved application release flow can update an immutable image without Terraform replacing it. A POC import therefore requires reconciling the live template with reviewed tfvars; a prior zero-diff claim made while the whole template was ignored is not proof of environment ownership.

## Phase 0 data and isolation contract

- The Agent, Adapter and Backoffice receive the same `AGENT_DEPLOYMENT_ENV` from `environment_name`; `prepare`, `activate` and `full` never appear as analytics environments.
- Raw conversation and handoff runtime defaults are 365 days. Firestore TTL policies delete documents only when the application writes `expiresAt` / `retentionExpiresAt`; the TTL index is not a backfill or legal-hold implementation. Shorter values are allowed only for controlled non-production TTL tests.
- `ai_ops_analytics.operational_events` is day-partitioned with a one-year expiration, required partition filters, and clustering by environment, tenant, event type and correlation ID. `operational_events_deduplicated` keeps the latest ingest for each immutable `event_id`.
- The Agent gets BigQuery job creation plus writer permission on the operational-events table only. The Backoffice gets job creation plus read access to the AI Ops dataset. Neither receives project-wide BigQuery `dataEditor`.
- `knowledge_portal_public_url` is a dedicated Portal setting. It is never copied from `adapter_public_base_url`; empty emits an explicit `KNOWLEDGE_PORTAL_URL_CONFIGURED=false` signal for the Backoffice.
- Terraform establishes storage and access boundaries only. Runtime masking, capability/data-scope enforcement, audit fail-closed behaviour and the reliable outbox remain application contracts. See [the infrastructure review](../../docs/ai-ops-infrastructure-review.md).

**Do not** run `deploy-gcp.sh` on Terraform-managed projects (`TERRAFORM_MANAGED=1`).

## New test project (greenfield)

```bash
# 0. Bootstrap state bucket (see ../environments/test/backend.hcl)
cp ../environments/test/terraform.tfvars.example infra/terraform/terraform.tfvars
# edit project_id, bot_client_id, bot_tenant_id — keep deployment_phase = "prepare"

./infra/scripts/terraform-prepare.sh infra/environments/test/backend.hcl
```

Inject secret **values**:

```bash
export GCP_PROJECT_ID=your-test-project-id
printf '%s' "$GOOGLE_API_KEY" | gcloud secrets versions add teams-agent-google-api-key --data-file=-
printf '%s' "$CLIENT_SECRET" | gcloud secrets versions add teams-agent-bot-client-secret --data-file=-
printf '%s' "$RAG_ASSET_SIGNING_KEY" | gcloud secrets versions add teams-agent-asset-signing-key --data-file=-
```

Build and push pinned images (Artifact Registry now exists; Cloud Run not required):

```bash
BUILD_ONLY=1 ./deploy/release-gcp.sh
```

Activate Cloud Run (set pinned images + `deployment_phase = "activate"` in tfvars):

```bash
./infra/scripts/terraform-activate.sh infra/environments/test/backend.hcl
```

Set `adapter_public_base_url` in tfvars, re-run activate apply, then smoke test:

```bash
curl -sS "$(terraform output -raw adapter_url)/readyz"
```

Subsequent app releases: `./deploy/release-gcp.sh` (without `BUILD_ONLY`).

## Import existing POC project

Use `environment_name = "poc"`, `deployment_phase = "full"` and `allow_latest_image_tags = true` in POC tfvars. Import with `[0]` addresses for Cloud Run resources — see [INVENTORY.md](./INVENTORY.md). Do not treat old import notes or reported plans as current cloud verification.

## Directory layout

```text
infra/
  terraform/              ← root module (this directory)
  environments/
    dev/ test/ poc/ prod/ ← isolated environment templates
  scripts/
    terraform-prepare.sh
    terraform-activate.sh
    terraform-plan-evidence.sh
  DEPLOYER_IAM.md
```

## CI

Pull requests run shell `bash -n` + ShellCheck, `terraform fmt -check`, provider lock consistency, and `terraform validate` (`.github/workflows/terraform.yml`).

## Handoff drill acceptance

A new engineer with repo + test project access should be able to:

1. Run prepare → inject secrets → `BUILD_ONLY=1` release → activate
2. Set `adapter_public_base_url` and verify `/readyz`
3. Run `deploy/release-gcp.sh` for a later SHA-tagged revision
4. Roll back one image revision

See [INVENTORY.md](./INVENTORY.md) for the POC import checklist. A real plan needs explicit authorization and the chosen environment's credentials/backend; do not run one merely from this repository.
