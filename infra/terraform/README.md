# Terraform — POC core infrastructure

Minimal, readable IaC for the Teams Agent POC on GCP. This describes **long-lived infrastructure** already provisioned by `deploy/deploy-gcp.sh`; it does **not** replace application release (image build/deploy) or secret **values**.

## Scope

| Managed by Terraform | Not managed by Terraform |
|---|---|
| Required GCP APIs | Secret **values** (API keys, client secrets) |
| Artifact Registry repository | Teams Developer Portal settings |
| Agent / Adapter service accounts | Knowledge bundle contents (`data/sources`, `data/index`) |
| IAM (Firestore, Secret Accessor, Run invoker) | Playground / Mock Ticket (optional UAT) |
| Secret Manager secret **containers** + IAM | Entra client secret value |
| Firestore database + TTL field policies | Production HA / VPC / WAF / DR |
| Cloud Run service **shape** (CPU, memory, env, SA, IAM) | Cloud Build job definitions (still in `deploy/`) |

## Ownership boundary

```text
terraform apply   → infrastructure shape, IAM, env vars, secret references
release pipeline  → build immutable image (commit SHA) + deploy revision
smoke test        → /readyz, Agent IAM, Teams E2E
```

Cloud Run **container images** are ignored after import (`lifecycle.ignore_changes` on `image`). Release updates images via `gcloud run deploy` or Cloud Build without fighting Terraform drift.

Do **not** let `deploy-gcp.sh` and Terraform both mutate the same knobs (CPU, env, IAM) on the live POC project once import is complete.

## Prerequisites

- Terraform >= 1.5
- `gcloud` authenticated to the target project
- Permission to create/read the resources in [INVENTORY.md](./INVENTORY.md)

## Quick start (new test project)

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars (project_id, bot_client_id, bot_tenant_id)

terraform init -backend-config=../environments/poc/backend.hcl
terraform plan
terraform apply
```

Inject secret **values** separately (CI, manual, or company secrets platform):

```bash
printf '%s' "$GOOGLE_API_KEY" | gcloud secrets versions add teams-agent-google-api-key --data-file=-
printf '%s' "$CLIENT_SECRET" | gcloud secrets versions add teams-agent-bot-client-secret --data-file=-
printf '%s' "$RAG_ASSET_SIGNING_KEY" | gcloud secrets versions add teams-agent-asset-signing-key --data-file=-
```

Build and release application images (see `deploy/README.md`).

## Import existing POC project (zero-diff goal)

**Do not `apply` to the live POC project until import reaches `Plan: 0 to add, 0 to change, 0 to destroy`.**

1. Bootstrap remote state bucket (one-time, documented in `../environments/poc/backend.hcl`).
2. Export live config (see INVENTORY.md § Audit commands).
3. Align `terraform.tfvars` with live non-secret settings (`adapter_public_base_url`, models, etc.).
4. `terraform init` + run import commands from [INVENTORY.md](./INVENTORY.md).
5. Repeat `terraform plan` until zero diff.

## Directory layout

```text
infra/
  terraform/          ← root module (this directory)
  environments/
    poc/
      backend.hcl
      terraform.tfvars.example
```

Staging / production modules can be extracted later; POC stays flat and readable.

## Knowledge artifact handoff (blocker outside Terraform)

Images embed `data/index/chunks.json` and assets at build time. Terraform cannot solve corpus provenance. Before handoff, document:

- Who owns source documents
- Where versioned knowledge bundles live
- How build selects a bundle version
- How to rebuild index and rollback

See `deploy/README.md` and repository `data/` layout.

## CI

Pull requests run `terraform fmt -check` and `terraform validate` (see `.github/workflows/terraform.yml`). `terraform plan` against GCP requires credentials and is intended for approved apply pipelines, not every PR.

## Handoff drill acceptance

A new engineer with repo + test project access (no developer laptop `.env`) should be able to:

1. `terraform init` / `plan` / `apply` on a **new** project
2. Inject secrets via documented commands
3. Deploy a pinned image revision
4. Verify `/readyz`, private Agent IAM, Firestore, RAG, Teams endpoint
5. Roll back one image revision

See INVENTORY.md for the resource mapping checklist.
