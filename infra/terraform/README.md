# Terraform — POC core infrastructure

Minimal, readable IaC for the Teams Agent POC on GCP. This describes **long-lived infrastructure**; it does **not** store secret **values** or replace application release (image build/deploy).

## Two workflows — do not mix them

| Workflow | Backend | tfvars example | Image policy |
|---|---|---|---|
| **POC import** (existing `deploy-gcp.sh` project) | `../environments/poc/backend.hcl` | `../environments/poc/terraform.tfvars.example` | `deployment_phase = "full"`, `allow_latest_image_tags = true` |
| **New test project** (clean-room handoff drill) | `../environments/test/backend.hcl` | `../environments/test/terraform.tfvars.example` | Two-phase bootstrap (see below) |

Each environment must use a **different GCS state bucket or at least a different prefix**. Never bootstrap a new test project against the POC backend.

Deployer / CI identities: [../DEPLOYER_IAM.md](../DEPLOYER_IAM.md).

## Deployment phases

Greenfield projects split Terraform into two applies so Artifact Registry and secret containers exist before images or Cloud Run:

| Phase | `deployment_phase` | Creates |
|---|---|---|
| **Prepare Environment** | `prepare` | APIs, Artifact Registry, service accounts, secret containers + IAM, Firestore, Agent Firestore IAM |
| **Activate Services** | `activate` | Cloud Run Agent + Adapter, Cloud Run IAM, runtime env, secret references |
| **POC import** | `full` | Everything at once (existing live stack) |

Wrapper scripts (no manual `-target`):

- `../scripts/terraform-prepare.sh [backend.hcl]`
- `../scripts/terraform-activate.sh [backend.hcl]`

## Scope

| Managed by Terraform | Not managed by Terraform |
|---|---|
| Required GCP APIs | Secret **values** (API keys, client secrets) |
| Artifact Registry repository | Teams Developer Portal settings |
| Agent / Adapter service accounts | Knowledge bundle contents (`data/sources`, `data/index`) |
| IAM (Firestore, Secret Accessor, Run invoker) | Playground / Mock Ticket (optional UAT) |
| Secret Manager secret **containers** + IAM | Entra client secret value |
| Firestore database + TTL field policies | Production HA / VPC / WAF / DR |
| Cloud Run service **shape** (CPU, memory, env, SA, IAM) | Cloud Build job definitions (in `deploy/`) |

## Ownership boundary

```text
terraform prepare  → foundation (no Cloud Run)
secret injection   → secret values
BUILD_ONLY release → push pinned images to Artifact Registry
terraform activate → Cloud Run shape + secret refs
release-gcp.sh     → subsequent immutable image updates only
smoke test         → /readyz, Agent IAM, Teams E2E
```

Cloud Run **container images** are ignored after import (`lifecycle.ignore_changes` on `image`).

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

## Import existing POC project (zero-diff goal)

Use `deployment_phase = "full"` and `allow_latest_image_tags = true` in poc tfvars. Import with `[0]` addresses for Cloud Run resources — see [INVENTORY.md](./INVENTORY.md).

## Directory layout

```text
infra/
  terraform/              ← root module (this directory)
  environments/
    poc/                  ← import existing POC (isolated state)
    test/                 ← new handoff drill project
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

See [INVENTORY.md](./INVENTORY.md) for the POC import checklist.
