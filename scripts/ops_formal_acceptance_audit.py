"""Read-only audit: schema validity, trusted LAB evidence, and formal decisions."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from ops_acceptance_evidence import (
    UTC,
    LAB_SELF_TEST,
    SPEC_CRITERIA,
    TrustedApprovalVerifier,
    TrustedTechnicalVerifier,
    formal_acceptance_errors,
    read_json,
    technical_verification_errors,
    validate_acceptance_evidence,
    write_json,
)


def build_audit(
    repo_root: Path, *, verifier: TrustedApprovalVerifier | None = None,
    technical_verifier: TrustedTechnicalVerifier | None = None,
    now: datetime | None = None, uat_report: dict | None = None,
    checklist: dict | None = None,
) -> dict[str, object]:
    if uat_report is None:
        path = repo_root / "artifacts/ai_ops_uat_acceptance_report.json"
        uat_report = read_json(path) if path.is_file() else {}
    if checklist is None:
        path = repo_root / "artifacts/ai_ops_signoff_checklist.json"
        checklist = read_json(path) if path.is_file() else {}
    evidence = uat_report.get("acceptanceEvidence")
    schema_errors = validate_acceptance_evidence(evidence, now=now)
    trusted_errors = technical_verification_errors(
        evidence, technical_verifier=technical_verifier, now=now,
    )
    classification = evidence.get("classification") if isinstance(evidence, dict) else "LEGACY_UNCLASSIFIED"
    lab_accepted = classification == LAB_SELF_TEST and not trusted_errors
    formal_errors = formal_acceptance_errors(
        checklist, uat_report, now=now, verifier=verifier, technical_verifier=technical_verifier,
    )
    return {
        "generatedAt": (now or datetime.now(UTC)).isoformat(),
        "assessmentScope": evidence.get("assessmentScope") if isinstance(evidence, dict) else None,
        "technicalSchemaValid": not schema_errors,
        "automatedVerificationPassed": lab_accepted,
        "automatedVerification": {
            "status": "TRUSTED_PASSED" if lab_accepted else (
                "SCHEMA_VALID_UNTRUSTED" if not schema_errors else "INVALID_OR_LEGACY_EVIDENCE"
            ),
            "schemaErrors": schema_errors,
            "trustedVerificationErrors": trusted_errors,
            "legacyReportedPassed": uat_report.get("automatedVerificationPassed", uat_report.get("passed")),
        },
        "labSelfTest": {"classification": classification, "accepted": lab_accepted},
        "formalAcceptanceComplete": not formal_errors,
        "formalAcceptance": {
            "complete": not formal_errors,
            "status": "COMPLETE_FOR_ASSESSED_TARGET" if not formal_errors else "PENDING_HUMAN_OR_EVIDENCE",
            "validationErrors": formal_errors,
        },
        "specCriteria": [
            {"id": key, "requirement": value, "status": "PENDING_EVIDENCE_OR_REVIEW" if formal_errors else "VERIFIED_FOR_TARGET"}
            for key, value in SPEC_CRITERIA.items()
        ],
        "limitations": [
            "Local JSON metadata and SHA256 do not authenticate a runner or an approval decision.",
            "Organisation-managed read-only runner/artifact and approval-decision adapters are required.",
            "Original phase specifications and unresolved governance decisions remain in force.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read acceptance evidence without executing checks.")
    parser.add_argument("--report", default="", help="New output path; existing evidence is protected.")
    parser.add_argument("--uat-report", default="", help="Explicit UAT evidence input.")
    parser.add_argument("--checklist", default="", help="Explicit formal evidence input.")
    parser.add_argument("--require-formal", action="store_true")
    args = parser.parse_args()
    try:
        audit = build_audit(
            Path(__file__).resolve().parents[1],
            uat_report=read_json(Path(args.uat_report)) if args.uat_report else None,
            checklist=read_json(Path(args.checklist)) if args.checklist else None,
        )
        if args.report:
            write_json(Path(args.report), audit)
        print(json.dumps(audit, indent=2, ensure_ascii=False))
    except (OSError, TypeError, ValueError) as exc:
        print(f"Cannot audit evidence: {exc}", file=sys.stderr)
        return 1
    return 1 if args.require_formal and not audit["formalAcceptanceComplete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
