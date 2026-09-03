# AI Ops acceptance evidence contract

Phase 0 and Phase 1 have two deliberately different outcomes:

- `LAB_SELF_TEST`: a reproducible technical execution in a named non-formal target. It can show that automated gates passed, but is never a BU, IT, Security/Legal, or Knowledge Admin approval.
- `FORMAL_ACCEPTANCE`: all required technical gates passed for the exact same target and all required organisations supplied externally verified approvals. It is the only classification eligible for `formalAcceptanceComplete`.

The legacy `status: approved`, `approvedBy`, `approvedAt`, and `notes` fields are review history only. They are not formal evidence, irrespective of the reviewer name or note language. In particular, the validator does not use Chinese/English keyword matching and does not infer authority from names.

## v2 evidence shape

Every v2 record contains an `acceptanceEvidence` object:

```json
{
  "schemaVersion": "v2",
  "classification": "LAB_SELF_TEST | FORMAL_ACCEPTANCE",
  "target": {
    "environment": "lab | test | poc | prod",
    "commitSha": "immutable source revision",
    "artifactIdentity": {"kind": "git-commit", "value": "immutable artifact/release identity"}
  },
  "expiresAt": "ISO-8601 timestamp",
  "technicalEvidence": {
    "requiredGateIds": ["pytest", "..."],
    "gates": [{
      "id": "pytest",
      "status": "PASSED",
      "command": "the executed command",
      "exitCode": 0,
      "executedAt": "ISO-8601 timestamp",
      "expiresAt": "ISO-8601 timestamp",
      "result": {"summary": "the observed result"},
      "artifactScope": {"target": "same target object", "references": ["result reference"]}
    }]
  }
}
```

The required baseline gates are `pytest`, `backup_verify`, `phase0_deliverables`, `terraform_validate`, `terraform_plan`, and `daily_reconciliation`. A gate is accepted only when it is recorded as `PASSED`, has the actual command and exit code `0`, a result summary, a target-matching artifact scope, and a current expiry. `SKIPPED`, `NOT_RUN`, a missing command, missing result, or a non-zero exit code always fail closed.

`executedAt`, `approvedAt`, and `verifiedAt` describe events that already happened: they must not be more than five minutes in the future and must be no older than 30 days. `expiresAt` must be in the future and after its associated event. This prevents both future-dated proof and stale evidence reuse.

## Formal approvals and trust

`FORMAL_ACCEPTANCE` additionally requires exactly these roles: `BU`, `IT`, `Security/Legal`, and `BU/Knowledge Admin`. Each approval contains a stable reviewer subject identifier, approval and expiry times, the exact reviewed target, and an `authorityEvidence` record with a source system and immutable source record id.

Fields such as `sourceSystem: "ENTRA_ACCESS_REVIEW"` and `verificationStatus: "EXTERNALLY_VERIFIED"` are schema claims only. They do not prove authority by themselves. The formal validator separately invokes a read-only `TrustedApprovalVerifier` adapter, which must query or cryptographically validate the organisation's authoritative approval record and confirm the reviewer, required role, source record, and target identity. The default local adapter returns pending-human-verification, so a JSON file cannot self-sign itself into formal completion. Test fakes only exercise this adapter boundary; they are not a production verifier.

An organisation may connect an Entra access-review, GRC workflow, or signed approval archive adapter after its trust and data-governance decision is approved. This repository does not invent that authority mapping.

## Migration and CLI behaviour

`ops_signoff_checklist.py --sync <checklist>` retains old `signOffItems` for audit compatibility and copies prior approved entries to `legacyApprovalRecords` with `trustStatus: UNVERIFIED_LEGACY`. It does not copy them into `formalApprovals`. Supplying `--output <new-file>` creates a separate migrated draft; omitting it is an explicit in-place local sync.

`ops_uat_handoff.py` writes no JSON unless `--report <new-path>` is supplied. It labels its output `LAB_SELF_TEST` and always sets `formalAcceptanceComplete` to `false`. Terraform plan output and audit output also require explicit new output paths. The read-only formal audit does not execute cloud actions, dispatch work, or create approvals.

For a formal review, retain the executed v2 LAB report, obtain the external approvals through the approved authority system, and run validation with an organisation-configured read-only verifier. Until that integration and the governance decision exist, the correct result is `formal approval pending`, not Phase 0/1 completion.
