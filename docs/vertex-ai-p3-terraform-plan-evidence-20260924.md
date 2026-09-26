# Vertex AI P3 Terraform plan evidence (2026-09-24)

> Lab/POC only. **Production is not cut over.** This note contains no secret values.

## How this repo runs Terraform

| Item | Value used this turn |
|---|---|
| Root module | `infra/terraform` |
| Lab/POC backend | `infra/environments/poc/backend.hcl` |
| State | `gs://itr-aimasteryhub-lab-terraform-state/poc/teams-agent` |
| Local tfvars | `infra/terraform/terraform.tfvars` (`project_id=itr-aimasteryhub-lab`, `region=asia-east1`, `deployment_phase=full`; `vertex_ai_project=itr-aimasteryhub-lab`; chat/embedding/PDF locations=`us`) |
| Wrapper | `infra/scripts/terraform-prepare.sh`, `terraform-activate.sh`, `terraform-plan-evidence.sh` |
| Command | `terraform init -backend-config=../environments/poc/backend.hcl -input=false -reconfigure` then `terraform plan -input=false -no-color` |

## Config gates required before this plan could run

Fail-closed now **accepts** the signed project/`us`. The first init this turn failed on invalid `depends_on = concat(...)` (Agent, Portal, Converter, Backoffice). Those lists are now static resource addresses. A follow-up `terraform validate` then hit a cycle (`image_policy` → computed Vision locals → converter URI → `image_policy`). `image_policy` now uses variable-only `vertex_pdf_in_play` and no longer reads `portal_pdf_converter_engine`.

## Post-import readonly plan (2026-09-24, after converter import)

**Success.** Terraform v1.16.0 against `itr-aimasteryhub-lab` / `asia-east1`. Refresh completed.

`Plan: 22 to add, 6 to change, 5 to destroy.`

Abort checks on that plan:

| Gate | Result |
|---|---|
| Fail-closed project/`us` | Plan proceeded. No missing-project or `global` error. |
| Converter / SA / Portal invoker | **In state after import.** `google_cloud_run_v2_service.pdf_converter[0]` is **update in-place**, not create. |
| Portal Vision | `KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE` / `URL` / `AUTH_MODE` were unchanged (`gemini_vision`, live URL, `GOOGLE_ID_TOKEN`). Not `legacy_text`. |
| Vertex env + key unmount | Agent, Portal, Converter, Backoffice planned `GEMINI_API_BACKEND=VERTEX_AI` and `VERTEX_AI_PROJECT=itr-aimasteryhub-lab` with locations `us`. Agent/Portal/Converter planned to unmount `GOOGLE_API_KEY`. Backoffice had no key mount. |
| API key secret resource | `google_secret_manager_secret.google_api_key` **no-op**. Planned destroys were only leftover `secretAccessor` IAM members. |
| Out-of-scope drift | Same plan would replace `google_bigquery_table.operational_events`, create `itr-aimasteryhub-lab-knowledge-ingestion`, enable Cloud Tasks, rewrite Portal ingestion/artifact env, and strip live Backoffice token/timeout/GCS env. **Not Vertex-only. Not applied.** |

`google_cloud_run_v2_service.adapter[0]` has no Gemini backend env (expected).

Historical first plan (before Vision contract / import): `21 to add, 5 to change, 5 to destroy` (would have parked Portal on `legacy_text`). Re-plan before import: `25 to add, 5 to change, 5 to destroy` (converter still **create**). Those counts are superseded.

## What was imported / applied (lab only)

Imported (were missing from state):

- `google_service_account.pdf_converter[0]`
- `google_cloud_run_v2_service.pdf_converter[0]`
- `google_cloud_run_v2_service_iam_member.portal_invokes_pdf_converter[0]`

Did **not** import `agent_google_api_key`.

Targeted Terraform apply (not the full 22/6/5 plan):

- Created `google_project_service.required["aiplatform.googleapis.com"]`
- Created `roles/aiplatform.user` for Agent, Portal, Converter, Backoffice SAs
- In-place updated Agent and Converter Cloud Run (Vertex env, unmount `GOOGLE_API_KEY`)
- Side effect of Agent/Converter `depends_on = [google_project_service.required]`: also created `cloudtasks.googleapis.com` in state (API enable only)

Portal and Backoffice were **not** applied via Terraform. Full Portal apply would have depended on the new ingestion bucket and stripped live env. Full Backoffice apply would have removed the live token and cut timeout `600s` → `60s`. Those two services were updated with `gcloud run services update --update-env-vars` (Portal also `--remove-secrets=GOOGLE_API_KEY`).

Leftover `secretAccessor` on `teams-agent-google-api-key` (Agent/Portal/Converter) and Portal on `google-api-key` was removed with `gcloud secrets remove-iam-policy-binding`. Secret **resources** remain. Stale Terraform IAM members were `state rm`'d. **Do not** `terraform destroy -target` those IAM members: that graph also tried to destroy Adapter/Portal; `deletion_protection` blocked it.

## Live revisions after cutover

| Service | Ready revision | `GEMINI_API_BACKEND` | Key mount | Notes |
|---|---|---|---|---|
| `teams-rag-agent` | `teams-rag-agent-00053-jdp` | `VERTEX_AI` | none | HYBRID stays. Tagged revision `workflow-routing` is not 100% traffic. |
| `teams-knowledge-portal` | `teams-knowledge-portal-00039-fjz` | `VERTEX_AI` | none | Still `gemini_vision` + `https://teams-pdf-converter-jt7pjdeeoa-de.a.run.app`. File Search sync/parity `false`/`false`. |
| `teams-pdf-converter` | `teams-pdf-converter-00004-79v` | `VERTEX_AI` | none | Same live digest as pin. PDF location `us`. |
| `teams-ai-ops-backoffice` | `teams-ai-ops-backoffice-00052-hw5` | `VERTEX_AI` | none | Live token/GCS/timeout left in place. |

`assert_bu_vertex_revision` passed on all four. `teams-agent-google-api-key` and `google-api-key` secret resources still exist.

## Remaining Terraform drift (do not treat as Vertex leftover work)

A later full plan will still want BigQuery `operational_events` replace, ingestion bucket create, Portal/Backoffice env convergence, and related IAM. Portal/Backoffice Cloud Run state now also drifts from the gcloud-only Vertex patch. Do not apply that drift unless separately authorized. The converter **targeted** plan is now No changes; that is not permission to apply the full-workspace plan.

`pdf_converter_image` in `infra/environments/poc/terraform.tfvars.example` and local `infra/terraform/terraform.tfvars` is now pinned to live `00008-zrb` digest `sha256:6c00f9f11a93f9f8a756c9ed9fadcb9f9b1dbd6ce28282d82a6fb005ace683a3`. That pin-only edit is **not** an apply. The historical plan table above still describes the post-import plan, not a new apply.

## Targeted converter-image plan (2026-09-24, superseded)

Command (lab/POC backend, local `infra/terraform/terraform.tfvars`):

```bash
terraform init -backend-config=../environments/poc/backend.hcl -input=false -reconfigure
terraform plan -input=false -no-color \
  -target='google_cloud_run_v2_service.pdf_converter[0]'
```

That earlier plan was `Plan: 0 to add, 1 to change, 0 to destroy.` Resource changes: converter **update in-place**; SA / `roles/aiplatform.user` / required APIs / `image_policy` **no-op**. The only planned diff was service-level `scaling` (`manual_instance_count=0`, `min_instance_count=0` → remove block). **Not applied.** Applying it would have minted a dummy converter revision for a non-Vertex field. Superseded by the alignment plan below.

## Targeted converter alignment (2026-09-24, No changes, no apply)

`google_cloud_run_v2_service.pdf_converter[0]` now ignores service-level `scaling` in `lifecycle.ignore_changes` (with image / `client` / `client_version`). Live gcloud revisions leave `manual_instance_count=0` / `min_instance_count=0`; that capacity is operational, not the Vertex env contract. Template-level min/max stays owned. Agent / Adapter / Backoffice still do **not** ignore service-level `scaling`.

Same command (lab/POC backend, local `infra/terraform/terraform.tfvars`):

```bash
terraform init -backend-config=../environments/poc/backend.hcl -input=false -reconfigure
terraform plan -input=false -no-color \
  -target='google_cloud_run_v2_service.pdf_converter[0]'
```

Quote:

```text
No changes. Your infrastructure matches the configuration.

Terraform has compared your real infrastructure against your configuration
and found no differences, so no changes are needed.
```

Refresh included converter Cloud Run, converter SA, `roles/aiplatform.user`, required APIs, and `image_policy`. No add / change / destroy. No BigQuery, no bucket, no Portal, no key remount, no converter create/replace, no new revision.

**Not applied.** An empty targeted plan is the alignment proof. Do not apply the full-workspace BigQuery / ingestion-bucket / Portal / Backoffice drift.

Terraform alignment for this Vertex converter target is **true**. The goal stays open because eval gates still lack a same-release baseline.
