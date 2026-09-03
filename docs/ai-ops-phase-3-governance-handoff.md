# AI Ops Backoffice Phase 3 governance handoff

This handoff covers the Phase 3 AI governance domain introduced under
`ai_ops_backoffice/governance_domain/`. It does not claim formal UAT sign-off.

## Delivered

- Immutable Prompt / Model / Feature Flag / Retention / Masking candidate lifecycle
- Deterministic Eval runner with critical safety gates
- Dual-control approve (submitter cannot approve)
- Prompt Canary percentage + sticky conversation routing
- Canary stop + metric evaluate (threshold auto-stop; keep active healthy)
- Atomic activate / rollback to previous healthy version
- Model allowlist, secret-ref-only storage, fallback simulation
- Safety-locked flags (`masking_enforced`, `audit_enforced`) cannot be disabled
- Production flags require expiry and revert to default after expiry
- Role-mapping requests cannot self-elevate; emergency principal revoke
- Capability-aware global search (Prompt/Model/Flag/Role/Retention/Masking/Audit + FAQ/Example/Issue/Quality extras)
- Governance audit trail with secret redaction and JSON audit export package
- Baseline import of code-based Issue Extractor prompt / model / flags
- Agent runtime wiring for prompt, model, and flags with fail-safe baselines
  (`PROMPT_RUNTIME_MODE=GOVERNED|CODE_BASELINE`)
- Backoffice UI pages for Prompt, models, flags, roles, retention, masking, search, audit export
- LAB drill script: `scripts/ops_phase3_governance_drill.py`
- SYSTEM_ADMIN single-approver sign-off helper: `scripts/ops_phase3_signoff.py`
- API surface under `/api/governance/*`

## Explicitly not claimed complete

- LLM-as-judge or cloud eval workers
- Legal hold
- Multi-approver quorum beyond dual control
- Continuous live production metric poller (evaluate is operator/API driven)
- Entra role mapping as sole source of truth in production
- Production Firestore multi-instance fault injection
- Unmasked conversation full-text search in global search

## Human sign-off policy (product decision)

Phase 3 does **not** require separate BU / security / audit signatures.
`SYSTEM_ADMIN` is the highest authority: one admin final approval is enough,
matching Phase 0/1. Technical gates (tests, dual-control on high-risk changes,
audit trail, passed LAB drill) still cannot be skipped by that approval.

```bash
cd agent_service
uv run python ../scripts/ops_phase3_governance_drill.py
python ../scripts/ops_phase3_signoff.py init
python ../scripts/ops_phase3_signoff.py approve --by Justin --notes "LAB drill reviewed"
python ../scripts/ops_phase3_signoff.py validate
```

## Agent runtime wiring

- `agent_service.prompt_runtime.GovernanceRuntime` resolves prompts, models, and flags.
- `ExtractorPromptRuntime` remains the Issue Extractor adapter.
- `peek_runtime_*` methods are read-only and never seed/write state.
- Missing store, invalid schema tokens, or lookup errors fall back to code/settings baselines.
- Ticket offers still require `ticket_service_mode != DISABLED`; governed `ticket_mode` default is `ENABLED`.
- Feedback / handoff / cost display combine settings with governed flags.
- Canary uses sticky `tenant + conversationId` bucketing.
- Env: `PROMPT_RUNTIME_MODE`, `AI_OPS_GOVERNANCE_STORE_MODE`, `AI_OPS_GOVERNANCE_STORE_PATH`.

## Key capabilities

Added to `agent_service.operations.access.CAPABILITIES` and
`data/ops/role_capability_matrix_v1.json`:

- `ops.prompts.eval.run|approve|canary|activate|rollback`
- `ops.models.read|write|approve|activate`
- `ops.flags.read|write|approve|activate`
- `ops.roles.request|approve|revoke`
- `ops.search.read`
- `ops.retention.read|write`
- `ops.audit.read`

## Persistence

`AI_OPS_GOVERNANCE_STORE_MODE=FILE|FIRESTORE` with default file path
`data/ops/phase3/governance.json`.
