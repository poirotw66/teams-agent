# AI Ops Backoffice Operations Runbook

Operational guide for Phase 0/1 monitoring, reconciliation, and incident response.
Traditional Chinese UI labels refer to the backoffice modules operators see in the browser.

## Service map (LAB)

| Component | Cloud Run service | Purpose |
|-----------|-------------------|---------|
| Backoffice | `teams-ai-ops-backoffice` | Operations dashboard, queries, exports |
| Agent | `teams-rag-agent` | RAG answers + operational event emission |
| Adapter | `teams-agent-adapter` | Teams bot ingress |

| Data store | Location | Contents |
|------------|----------|----------|
| Firestore `operational_events` | `itr-aimasteryhub-lab` | Immutable ops events (primary read path) |
| Firestore `audit_events` | same | Audit trail |
| BigQuery `ai_ops_analytics.operational_events` | same | Analytics / reconciliation |
| BigQuery `ai_ops_logs` | same | Cloud Run structured log exports |

Inventory: `infra/ai-ops-environment-inventory.json`

## Daily operations

### 1. Reconciliation (required)

```bash
cd agent_service
uv run python ../scripts/ops_daily_reconciliation.py --preset 30d
```

Expect `allMatch: true`. Investigate when conversation or issue counts diverge from deduplicated raw events.

### 2. UAT / handoff bundle (LAB or pre-release)

```bash
cd agent_service
uv run python ../scripts/ops_uat_handoff.py \
  --gcp-project itr-aimasteryhub-lab \
  --live-url https://teams-ai-ops-backoffice-jt7pjdeeoa-de.a.run.app
```

Artifacts land in `artifacts/ai_ops_uat_acceptance_report.json`.

### 3. BU acceptance walkthrough (Phase 1 §15)

Scripted equivalent of the manual task: **負評 → 對話 → Issue → 來源文件**.

```bash
python scripts/ops_bu_walkthrough.py \
  --base-url https://teams-ai-ops-backoffice-jt7pjdeeoa-de.a.run.app \
  --report artifacts/ops_bu_walkthrough.json
```

If no negative feedback exists, seed demo data first:

```bash
cd agent_service
OPS_STORE_MODE=FIRESTORE OPS_FIRESTORE_PROJECT=itr-aimasteryhub-lab \
  uv run --extra firestore python ../scripts/ops_seed_lab_demo.py --project itr-aimasteryhub-lab
```

## Monitoring

### GCP Monitoring dashboard

Terraform manages `google_monitoring_dashboard.ai_ops`:

- Backoffice request rate
- Backoffice 5xx errors
- Backoffice latency P95

Open: GCP Console → Monitoring → Dashboards → **AI Ops Backoffice**

### Alert policy

`google_monitoring_alert_policy.backoffice_5xx` fires when 5xx rate exceeds threshold for 5 minutes.
Configure `ops_alert_email` in Terraform tfvars to receive notifications.

### Log sinks

| Sink | Filter | Destination |
|------|--------|-------------|
| `ai-ops-backoffice-logs` | `teams-ai-ops-backoffice` revisions | `ai_ops_logs` BQ dataset |
| `ai-ops-agent-logs` | `teams-rag-agent` revisions | `ai_ops_logs` BQ dataset |

Verify:

```bash
gcloud logging sinks describe ai-ops-backoffice-logs --project=itr-aimasteryhub-lab
gcloud logging sinks describe ai-ops-agent-logs --project=itr-aimasteryhub-lab
```

Or run from `agent_service`:

```bash
uv run --extra firestore --extra bigquery python ../scripts/ops_gcp_verification.py \
  --project itr-aimasteryhub-lab \
  --report ../artifacts/ai_ops_gcp_verification.json
```

## Incident response

### Symptom: Dashboard shows zero conversations but Agent is live

1. Confirm Agent `OPS_EVENTS_ENABLED=true` and `OPS_STORE_MODE=FIRESTORE`.
2. Run GCP verification and reconciliation scripts.
3. Check Firestore `operational_events` collection for recent writes.
4. For LAB demos, run `ops_seed_lab_demo.py`.

### Symptom: Backoffice 5xx alert

1. Check Cloud Run logs for `teams-ai-ops-backoffice`.
2. Confirm Firestore and taxonomy paths are reachable.
3. Roll back to previous image if a bad deploy; Terraform ignores template drift on import POC.

### Symptom: Export fails or audit missing

Exports are fail-closed when audit write fails. Check `audit_events` collection and backoffice service account Firestore permissions.

Production export storage must be configured explicitly:

```bash
AI_OPS_EXPORT_JOB_STORE_MODE=FIRESTORE
AI_OPS_EXPORT_JOB_COLLECTION=ai_ops_export_jobs
AI_OPS_EXPORT_CONTENT_BACKEND=GCS
AI_OPS_EXPORT_GCS_BUCKET=<private-export-bucket>
AI_OPS_EXPORT_TTL_SECONDS=86400
AI_OPS_EXPORT_MAX_RECORDS=100000
```

The backoffice sweeps expired exports every 60 seconds and removes both artifact bytes and the persisted result payload. A GCS backend without `AI_OPS_EXPORT_GCS_BUCKET` fails during startup instead of falling back to local storage.

### Symptom: Masking or unauthorized access concern

1. Review audit events: `GET /api/audit-events` as `AUDITOR`.
2. Unmasked conversation access requires `ops.conversations.unmasked` capability and `unmask_reason` query param.
3. Escalate to security/legal per data classification policy.

## Data retention and purge

TTL fields are set on Firestore collections via Terraform. Test purge in non-prod:

```bash
# Admin API (requires SYSTEM_ADMIN capability)
POST /api/admin/retention/purge
```

Automated test: `tests/test_operations_phase0.py::test_purge_expired_events_removes_only_expired_records`

## Backup and recovery

Prerequisite check:

```bash
python scripts/ops_backup_verify.py --project itr-aimasteryhub-lab
```

Recovery commands are printed by that script (Firestore export, BQ copy, replay).

## Terraform handoff

```bash
cd infra/terraform
terraform init -backend-config=../environments/poc/backend.hcl
terraform plan   # expect: No changes
```

Import checklist: `infra/terraform/INVENTORY.md`

## Sign-off checklist (manual)

Formal acceptance (Phase 0 §17, Phase 1 §15) requires four human approvals recorded in `artifacts/ai_ops_signoff_checklist.json`.

**Non-technical walkthrough (Traditional Chinese):** `docs/ai-ops-signoff-walkthrough-zh.md`

### 1. BU — taxonomy and metrics (`bu-taxonomy-metrics`)

Review artifacts:

- `data/ops/issue_taxonomy_v1.json` — issue types and ownership
- `data/ops/metrics_definitions_v1.json` — KPI definitions and drill-down links

Confirm definitions match operational needs, then set `status: "approved"`, `approvedBy`, and `approvedAt` on the checklist item.

### 2. IT — Terraform (`it-terraform`)

```bash
cd infra/terraform
terraform init -backend-config=../environments/poc/backend.hcl
terraform plan   # expect: No changes
```

Evidence: `artifacts/terraform-ai-ops-plan-evidence.txt` (regenerated by UAT handoff).

### 3. Security/Legal — masking, retention, export (`security-masking-retention`)

Review:

- `data/ops/data_governance_decisions_v1.json`
- `data/ops/role_capability_matrix_v1.json`
- Export fail-closed test: `tests/test_ai_ops_backoffice.py::test_export_audit_fail_closed`
- Unmask step-up: `tests/test_ai_ops_backoffice.py::test_conversation_unmask_requires_capability_and_reason`

### 4. Knowledge Portal governance UAT (`knowledge-portal-governance`)

Manual BU walkthrough on LAB Knowledge Portal:

1. Import or edit a Markdown document, submit for review, publish.
2. Import a **text** PDF (not scanned), publish.
3. Confirm backoffice Knowledge module shows governance status for both documents.

Automated coverage: `tests/test_ai_ops_portal_governance_integration.py`.

### Validate and close

Record each approval (repeat for all four items):

```bash
python scripts/ops_signoff_approve.py \
  --checklist artifacts/ai_ops_signoff_checklist.json \
  --item bu-taxonomy-metrics \
  --by "Service Owner Name" \
  --notes "Reviewed taxonomy v1 and metrics on LAB."
```

Then validate and close:

```bash
python scripts/ops_signoff_checklist.py --validate artifacts/ai_ops_signoff_checklist.json

python scripts/ops_signoff_evidence.py --report artifacts/ai_ops_signoff_evidence.json

cd agent_service
uv run python ../scripts/ops_uat_handoff.py \
  --gcp-project itr-aimasteryhub-lab \
  --live-url https://teams-ai-ops-backoffice-jt7pjdeeoa-de.a.run.app \
  --require-signoff
```

Note: UAT handoff uses `--sync` on the checklist so re-runs preserve existing approvals.

- Evidence report: `artifacts/ai_ops_uat_acceptance_report.json`
- Sign-off evidence packet: `artifacts/ai_ops_signoff_evidence.json`
- Sign-off checklist: `artifacts/ai_ops_signoff_checklist.json`
