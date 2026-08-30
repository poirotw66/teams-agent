# Terraform — POC core infrastructure

Minimal, readable IaC for the Teams Agent POC on GCP. This describes **long-lived infrastructure**; it does **not** store secret **values** or replace application release (image build/deploy).

## Two workflows — do not mix them

| Workflow | Backend | tfvars example | Image policy |
|---|---|---|---|
| **POC import** (existing `deploy-gcp.sh` project) | `../environments/poc/backend.hcl` | `../environments/poc/terraform.tfvars.example` | `allow_latest_image_tags = true` during import only |
| **New test project** (clean-room handoff drill) | `../environments/test/backend.hcl` | `../environments/test/terraform.tfvars.example` | **Pinned** `agent_image` / `adapter_image` (SHA or digest) |

Each environment must use a **different GCS state bucket or at least a different prefix**. Never bootstrap a new test project against the POC backend.

Deployer / CI identities: [../DEPLOYER_IAM.md](../DEPLOYER_IAM.md).

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
terraform apply   → infrastructure shape, IAM, env vars, secret references
release-gcp.sh    → build immutable image (commit SHA) + Cloud Run image update only
smoke test        → /readyz, Agent IAM, Teams E2E
```

Cloud Run **container images** are ignored after import (`lifecycle.ignore_changes` on `image`). Release updates images via `deploy/release-gcp.sh` without fighting Terraform drift.

**Do not** run `deploy-gcp.sh` on Terraform-managed projects (`TERRAFORM_MANAGED=1`). It still mutates IAM, secrets, CPU, env, scaling, and timeout.

## Suggested completion order

1. Ensure `backend "gcs" {}` in `versions.tf` (done).
2. Bootstrap the correct environment backend bucket + prefix.
3. Copy the matching `terraform.tfvars.example` → `terraform.tfvars`.
4. **POC:** import all live resources ([INVENTORY.md](./INVENTORY.md)).
5. Run `terraform plan` until `0 to add, 0 to change, 0 to destroy`.
6. Save evidence: `../scripts/terraform-plan-evidence.sh`.
7. Use `deploy/release-gcp.sh` for image releases (not `deploy-gcp.sh`).
8. Run a clean-room handoff drill on a **test** project with pinned images.
9. Declare Terraform handoff complete.

## New test project (greenfield)

```bash
cd infra/terraform

# 1. Bootstrap state in the TEST project (see ../environments/test/backend.hcl)
# 2. Copy tfvars — must pin images; allow_latest_image_tags stays false
cp ../environments/test/terraform.tfvars.example terraform.tfvars
# edit project_id, bot IDs, agent_image, adapter_image

terraform init -backend-config=../environments/test/backend.hcl
terraform plan
terraform apply
```

Inject secret **values** separately:

```bash
printf '%s' "$GOOGLE_API_KEY" | gcloud secrets versions add teams-agent-google-api-key --data-file=-
printf '%s' "$CLIENT_SECRET" | gcloud secrets versions add teams-agent-bot-client-secret --data-file=-
printf '%s' "$RAG_ASSET_SIGNING_KEY" | gcloud secrets versions add teams-agent-asset-signing-key --data-file=-
```

Build and release application images:

```bash
export GCP_PROJECT_ID=your-test-project-id
./deploy/release-gcp.sh
```

After apply, set `adapter_public_base_url` in tfvars if not passed on first apply, then re-apply.

## Import existing POC project (zero-diff goal)

**Do not `apply` to the live POC project until import reaches `Plan: 0 to add, 0 to change, 0 to destroy`.**

```bash
cd infra/terraform
cp ../environments/poc/terraform.tfvars.example terraform.tfvars
# align bot IDs, adapter_public_base_url, allow_latest_image_tags = true

terraform init -backend-config=../environments/poc/backend.hcl
# run imports from INVENTORY.md
terraform plan
```

When plan is clean, export evidence and switch releases to `release-gcp.sh` with `TERRAFORM_MANAGED=1` on POC.

## Directory layout

```text
infra/
  terraform/              ← root module (this directory)
  environments/
    poc/                  ← import existing POC (isolated state)
    test/                 ← new handoff drill project
  scripts/
    terraform-plan-evidence.sh
  DEPLOYER_IAM.md
```

## CI

Pull requests run `terraform fmt -check`, provider lock consistency check, and `terraform validate` (`.github/workflows/terraform.yml`). `terraform plan` against GCP requires credentials and belongs in approved apply pipelines.

## Handoff drill acceptance

A new engineer with repo + test project access (no developer laptop `.env`) should be able to:

1. `terraform init` / `plan` / `apply` on a **new** project with **pinned images**
2. Inject secrets via documented commands
3. Run `deploy/release-gcp.sh` for a SHA-tagged revision
4. Verify `/readyz`, private Agent IAM, Firestore, RAG, Teams endpoint (`terraform output teams_developer_portal_runbook`)
5. Roll back one image revision (release script rolls back on failure; manual rollback via previous image tag)

See [INVENTORY.md](./INVENTORY.md) for the resource mapping checklist.
