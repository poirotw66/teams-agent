# Deployer and CI identities

Document who may run Terraform, build images, release revisions, and inject secret values. Terraform can materialize these service accounts later; this file is the handoff contract.

## Principle

| Activity | Identity | Typical human approver |
|---|---|---|
| Terraform plan (read-only) | Terraform plan SA or engineer with Viewer + custom read roles | — |
| Terraform apply (shape change) | Terraform apply SA | Platform / SRE lead |
| Cloud Build (image build) | Cloud Build default SA or dedicated build SA | Release engineer |
| Artifact Registry push | Cloud Build SA or release SA | — |
| Cloud Run image update | Release deployer SA | Release engineer |
| Secret version inject | Secret admin SA (values only) | Security / bot owner |
| Service Account User (`roles/iam.serviceAccountUser`) | Release deployer SA on runtime SAs | Platform |

Runtime service accounts (`teams-rag-agent`, `teams-agent-adapter`) are **not** deployer identities. They run the application only.

## Recommended service accounts (per environment project)

| Account ID | Purpose |
|---|---|
| `terraform-plan@…` | `terraform plan`, state read, resource inventory |
| `terraform-apply@…` | `terraform apply` on approved changes |
| `release-deployer@…` | `deploy/release-gcp.sh` — Cloud Build submit, AR write, Cloud Run update |
| `secret-injector@…` | `gcloud secrets versions add` only (no Terraform) |

POC may temporarily use human `gcloud` credentials for import; production should use workload identity / CI impersonation.

## Minimum IAM bindings

### `terraform-plan@`

- `roles/viewer` on project (or curated read-only custom role)
- `roles/storage.objectViewer` on `{project}-terraform-state` bucket
- Optional: `roles/iam.securityReviewer`

### `terraform-apply@`

Everything plan needs, plus:

- `roles/editor` **or** a custom role limited to resources in [INVENTORY.md](../terraform/INVENTORY.md)
- `roles/storage.objectAdmin` on the environment state bucket/prefix
- `roles/iam.serviceAccountAdmin` (create runtime SAs if greenfield)
- `roles/secretmanager.admin` for secret **containers** only (not reading secret values in CI logs)

Human approval gate: apply pipeline requires manual approval or protected environment.

### Cloud Build / release (`release-deployer@`)

- `roles/cloudbuild.builds.editor`
- `roles/artifactregistry.writer` on `teams-agent` repository
- `roles/run.developer` on Agent and Adapter services
- `roles/iam.serviceAccountUser` on:
  - `teams-rag-agent@…`
  - `teams-agent-adapter@…`
- `roles/logging.logWriter` (Cloud Build logs)

Does **not** need Secret Manager write, Firestore admin, or project IAM admin.

### `secret-injector@`

- `roles/secretmanager.secretVersionManager` on:
  - `teams-agent-google-api-key`
  - `teams-agent-bot-client-secret`
  - `teams-agent-asset-signing-key`

Humans with this role inject values after Terraform creates empty secret containers. Values never enter Terraform state.

## Workflow separation

```text
terraform apply (apply SA)     → APIs, AR repo, runtime SAs, IAM, secret containers, Firestore, Cloud Run shape
secret-injector (injector SA)  → secret values via gcloud
release-gcp.sh (release SA)    → build + push SHA-tagged images + Cloud Run image update only
```

Do **not** run `deploy/deploy-gcp.sh` when `TERRAFORM_MANAGED=1`. It mutates IAM, secrets, CPU, env, and scaling — outside the release boundary.

## State bucket isolation

| Environment | Backend config | Bucket (example) | Prefix |
|---|---|---|---|
| POC import | `infra/environments/poc/backend.hcl` | `itr-aimasteryhub-lab-terraform-state` | `poc/teams-agent` |
| Test / handoff drill | `infra/environments/test/backend.hcl` | `<test-project>-terraform-state` | `test/teams-agent` |

Never point a new test project at the POC backend.

## Audit evidence

After import, save a redacted plan:

```bash
./infra/scripts/terraform-plan-evidence.sh ../environments/poc/backend.hcl plan-evidence.txt
```

Attach `plan-evidence.txt` to the handoff ticket (no secret values, no tfvars).

## Future Terraform work

- Create the four SAs above per environment module
- Wire GitHub Actions / Cloud Build triggers to impersonate `release-deployer@`
- Add production-only policy scanner, cost estimate, and apply approval gate (not required for POC)
