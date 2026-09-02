#!/usr/bin/env python3
"""Generate, sync, or validate the manual sign-off checklist for formal acceptance.

Usage:
    python scripts/ops_signoff_checklist.py --write artifacts/ai_ops_signoff_checklist.json
    python scripts/ops_signoff_checklist.py --sync artifacts/ai_ops_signoff_checklist.json
    python scripts/ops_signoff_checklist.py --validate artifacts/ai_ops_signoff_checklist.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _default_checklist(repo_root: Path) -> dict[str, object]:
    ops_dir = repo_root / "data" / "ops"
    return {
        "checklistVersion": "v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "specReferences": [
            "docs/ai-ops-backoffice-phase-0-foundation-spec.md §17",
            "docs/ai-ops-backoffice-phase-1-operations-mvp-spec.md §15",
        ],
        "automatedEvidence": {
            "uatAcceptanceReport": str(repo_root / "artifacts/ai_ops_uat_acceptance_report.json"),
            "terraformPlanEvidence": str(repo_root / "artifacts/terraform-ai-ops-plan-evidence.txt"),
            "gcpVerificationReport": str(repo_root / "artifacts/ai_ops_gcp_verification.json"),
            "buWalkthroughReport": str(repo_root / "artifacts/ops_bu_walkthrough.json"),
            "runbook": str(repo_root / "docs/ai-ops-backoffice-runbook.md"),
            "environmentInventory": str(repo_root / "infra/ai-ops-environment-inventory.json"),
        },
        "signOffItems": [
            {
                "id": "bu-taxonomy-metrics",
                "role": "BU",
                "description": "Approve issue taxonomy v1 and metric definitions",
                "status": "pending",
                "approvedBy": "",
                "approvedAt": "",
                "notes": "",
                "reviewArtifacts": [
                    str(ops_dir / "issue_taxonomy_v1.json"),
                    str(ops_dir / "metrics_definitions_v1.json"),
                    str(ops_dir / "issue_classification_rules.json"),
                    "scripts/ops_deliverables_verify.py",
                ],
            },
            {
                "id": "it-terraform",
                "role": "IT",
                "description": "Approve Terraform state and zero-diff plan in target environment",
                "status": "pending",
                "approvedBy": "",
                "approvedAt": "",
                "notes": "",
                "reviewArtifacts": [
                    "infra/terraform/INVENTORY.md",
                    str(repo_root / "infra/ai-ops-environment-inventory.json"),
                    str(repo_root / "artifacts/terraform-ai-ops-plan-evidence.txt"),
                ],
            },
            {
                "id": "security-masking-retention",
                "role": "Security/Legal",
                "description": "Approve masking, retention, export, and audit policy",
                "status": "pending",
                "approvedBy": "",
                "approvedAt": "",
                "notes": "",
                "reviewArtifacts": [
                    str(ops_dir / "data_governance_decisions_v1.json"),
                    str(ops_dir / "role_capability_matrix_v1.json"),
                    "agent_service/tests/test_ai_ops_backoffice.py::test_export_audit_fail_closed",
                    "agent_service/tests/test_ai_ops_backoffice.py::test_conversation_unmask_requires_capability_and_reason",
                    "agent_service/tests/test_operations_phase0.py::test_purge_expired_events_removes_only_expired_records",
                ],
            },
            {
                "id": "knowledge-portal-governance",
                "role": "BU/Knowledge Admin",
                "description": "Complete Knowledge Portal markdown and text PDF publish UAT (§12.7)",
                "status": "pending",
                "approvedBy": "",
                "approvedAt": "",
                "notes": (
                    "Automated portal→backoffice governance tests cover markdown and text PDF; "
                    "confirm publish workflow on target Knowledge Portal before approving."
                ),
                "reviewArtifacts": [
                    "agent_service/tests/test_ai_ops_portal_governance_integration.py",
                    "agent_service/tests/test_knowledge_portal.py::test_pdf_publish_workflow",
                    "agent_service/tests/test_knowledge_portal.py::test_import_text_pdf",
                ],
            },
        ],
    }


def _merge_sign_off_items(
    existing_items: list[dict[str, object]] | None,
    fresh_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not existing_items:
        return fresh_items

    preserved = {
        str(item.get("id", "")): item
        for item in existing_items
        if isinstance(item, dict) and item.get("id")
    }
    merged: list[dict[str, object]] = []
    for fresh in fresh_items:
        item_id = str(fresh.get("id", ""))
        previous = preserved.get(item_id)
        if previous is None:
            merged.append(fresh)
            continue
        merged_item = dict(fresh)
        for field in ("status", "approvedBy", "approvedAt", "notes"):
            if str(previous.get(field, "")).strip():
                merged_item[field] = previous[field]
        merged.append(merged_item)
    return merged


def sync_checklist(repo_root: Path, path: Path) -> dict[str, object]:
    fresh = _default_checklist(repo_root)
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing_items = existing.get("signOffItems")
        if isinstance(existing_items, list):
            fresh["signOffItems"] = _merge_sign_off_items(existing_items, fresh["signOffItems"])
    return fresh


def _validate_checklist(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    items = payload.get("signOffItems")
    if not isinstance(items, list):
        return ["signOffItems must be a list"]
    for item in items:
        if not isinstance(item, dict):
            errors.append("each signOffItem must be an object")
            continue
        if item.get("status") != "approved":
            errors.append(f"{item.get('id', 'unknown')} is not approved")
            continue
        if not str(item.get("approvedBy", "")).strip():
            errors.append(f"{item.get('id', 'unknown')} missing approvedBy")
        if not str(item.get("approvedAt", "")).strip():
            errors.append(f"{item.get('id', 'unknown')} missing approvedAt")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage AI Ops formal acceptance sign-off checklist.")
    parser.add_argument("--write", default="", help="Write a fresh checklist JSON to path.")
    parser.add_argument(
        "--sync",
        default="",
        help="Refresh checklist metadata while preserving existing approvals.",
    )
    parser.add_argument("--validate", default="", help="Validate checklist JSON has all approvals.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    if args.write:
        path = Path(args.write)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_default_checklist(repo_root), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote sign-off checklist to {path}")
        return 0

    if args.sync:
        path = Path(args.sync)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = sync_checklist(repo_root, path)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Synced sign-off checklist to {path}")
        return 0

    if args.validate:
        path = Path(args.validate)
        if not path.is_file():
            print(f"Checklist not found: {path}", file=sys.stderr)
            return 1
        payload = json.loads(path.read_text(encoding="utf-8"))
        errors = _validate_checklist(payload)
        if errors:
            for error in errors:
                print(f"  [FAIL] {error}")
            print(f"\nSign-off checklist incomplete ({len(errors)} issue(s)).", file=sys.stderr)
            return 1
        print("Sign-off checklist validation passed.")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
