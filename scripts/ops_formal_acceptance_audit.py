#!/usr/bin/env python3
"""Print a requirement-by-requirement formal acceptance audit.

Maps Phase 0/1 spec criteria to evidence and reports automated vs manual status.

Usage:
    python scripts/ops_formal_acceptance_audit.py
    python scripts/ops_formal_acceptance_audit.py --report artifacts/ai_ops_formal_acceptance_audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _read_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_audit(repo_root: Path) -> dict[str, object]:
    uat_report = _read_json(repo_root / "artifacts/ai_ops_uat_acceptance_report.json") or {}
    signoff = _read_json(repo_root / "artifacts/ai_ops_signoff_checklist.json") or {}
    signoff_items = signoff.get("signOffItems", [])
    pending_signoffs = [
        str(item.get("id"))
        for item in signoff_items
        if isinstance(item, dict) and item.get("status") != "approved"
    ]

    phase0_criteria = [
        {"id": "P0-14.1", "description": "Turn events linkable by ID", "status": "automated", "evidence": "tests/test_operations_integrations.py"},
        {"id": "P0-14.2", "description": "Duplicate eventId does not increase counts", "status": "automated", "evidence": "tests/test_operations_phase0.py"},
        {"id": "P0-14.3", "description": "Metric definitions document KPI calculations", "status": "automated", "evidence": "data/ops/metrics_definitions_v1.json"},
        {"id": "P0-14.4", "description": "20-50 active issue types with owner", "status": "automated", "evidence": "scripts/ops_deliverables_verify.py"},
        {"id": "P0-14.5", "description": "Unclassified issues route to other.unclassified", "status": "automated", "evidence": "data/ops/issue_taxonomy_v1.json"},
        {"id": "P0-14.6", "description": "Unauthorized roles cannot access unmasked data", "status": "automated", "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_actor_ref_conversation_lookup"},
        {"id": "P0-14.7", "description": "Credentials excluded from analytics and audit", "status": "automated", "evidence": "tests/test_operations_phase0.py::test_masking_redacts_email_and_credentials"},
        {"id": "P0-14.8", "description": "TTL purge removes expired records only", "status": "automated", "evidence": "tests/test_operations_phase0.py::test_purge_expired_events_removes_only_expired_records"},
        {"id": "P0-14.9", "description": "High-risk operations fail closed on audit write failure", "status": "automated", "evidence": "tests/test_ai_ops_backoffice.py::test_export_audit_fail_closed"},
        {"id": "P0-14.10", "description": "Environment and Terraform state isolation", "status": "automated", "evidence": "infra/ai-ops-environment-inventory.json; artifacts/terraform-ai-ops-plan-evidence.txt"},
    ]

    phase1_criteria = uat_report.get("phase1AcceptanceCriteria", [])
    phase0_dod = [
        {"id": "P0-17.1", "description": "BU/IT/Security approve metrics and governance", "status": "manual", "evidence": "artifacts/ai_ops_signoff_checklist.json"},
        {"id": "P0-17.2", "description": "Taxonomy usable by agent mapping", "status": "automated", "evidence": "data/ops/issue_classification_rules.json"},
        {"id": "P0-17.3", "description": "Schema-valid idempotent events on key paths", "status": "automated", "evidence": "scripts/ops_gcp_verification.py"},
        {"id": "P0-17.4", "description": "Storage, TTL, masking, auth, audit tests pass", "status": "automated", "evidence": "tests/test_operations_phase0.py; tests/test_ai_ops_backoffice.py"},
        {"id": "P0-17.5", "description": "Terraform plan and inventory handoff ready", "status": "automated", "evidence": "infra/terraform/INVENTORY.md"},
        {"id": "P0-17.6", "description": "Phase 1 built on Phase 0 contracts without redefinition", "status": "automated", "evidence": "tests/test_ai_ops_backoffice_acceptance.py"},
    ]
    phase1_dod = [
        {"id": "P1-15.1", "description": "Phase 1 metrics reconcile with Phase 0 definitions", "status": "automated", "evidence": "scripts/ops_daily_reconciliation.py"},
        {"id": "P1-15.2", "description": "Role, scope, masking, export security tests pass", "status": "automated", "evidence": "tests/test_ai_ops_backoffice_acceptance.py"},
        {"id": "P1-15.3", "description": "UI loading/empty/error/forbidden states", "status": "automated", "evidence": "src/ai_ops_backoffice/static/js/main.js"},
        {"id": "P1-15.4", "description": "Markdown/PDF governance E2E UAT", "status": "manual", "evidence": "signOffItems/knowledge-portal-governance"},
        {"id": "P1-15.5", "description": "Monitoring and runbook in place", "status": "automated", "evidence": "docs/ai-ops-backoffice-runbook.md; infra/terraform/ai_ops_monitoring.tf"},
        {"id": "P1-15.6", "description": "BU 15-minute negative-feedback drill-down", "status": "automated", "evidence": "scripts/ops_bu_walkthrough.py"},
    ]

    automated_complete = bool(
        uat_report.get("automatedVerificationPassed", uat_report.get("passed"))
    )
    # Stale reports may predate automatedVerificationPassed; infer from step results.
    if not automated_complete:
        steps = uat_report.get("steps", [])
        if isinstance(steps, list):
            automated_failed = [
                step.get("name")
                for step in steps
                if isinstance(step, dict)
                and step.get("name")
                not in ("signoff_validation", "formal_acceptance_audit")
                and step.get("exitCode") not in (0, None)
            ]
            automated_complete = len(automated_failed) == 0 and bool(steps)
    formal_complete = bool(uat_report.get("formalAcceptanceComplete")) and not pending_signoffs

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "automatedVerificationPassed": automated_complete,
        "formalAcceptanceComplete": formal_complete,
        "pendingManualSignOffs": pending_signoffs,
        "phase0AcceptanceCriteria": phase0_criteria,
        "phase1AcceptanceCriteria": phase1_criteria,
        "phase0DefinitionOfDone": phase0_dod,
        "phase1DefinitionOfDone": phase1_dod,
        "blockingItems": pending_signoffs if not formal_complete else [],
        "closeOutCommand": (
            "cd agent_service && uv run python ../scripts/ops_uat_handoff.py "
            "--gcp-project itr-aimasteryhub-lab "
            "--live-url https://teams-ai-ops-backoffice-jt7pjdeeoa-de.a.run.app "
            "--require-signoff"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit AI Ops formal acceptance status.")
    parser.add_argument("--report", default="", help="Optional JSON output path.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    audit = build_audit(repo_root)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote formal acceptance audit to {report_path}")

    print(f"Automated verification: {'PASS' if audit['automatedVerificationPassed'] else 'FAIL'}")
    print(f"Formal acceptance: {'COMPLETE' if audit['formalAcceptanceComplete'] else 'INCOMPLETE'}")
    if audit["pendingManualSignOffs"]:
        print("Pending sign-offs:", ", ".join(str(item) for item in audit["pendingManualSignOffs"]))

    if audit["formalAcceptanceComplete"]:
        return 0
    if audit["automatedVerificationPassed"]:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
