#!/usr/bin/env python3
"""Phase 3 SYSTEM_ADMIN single-approver sign-off helper.

Product policy: one SYSTEM_ADMIN final approval is enough (same as Phase 0/1).
Technical drill evidence must pass before milestone validation succeeds.

Usage:
    python scripts/ops_phase3_signoff.py init
    python scripts/ops_phase3_signoff.py approve --by Justin --notes "LAB drill reviewed"
    python scripts/ops_phase3_signoff.py validate
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PHASE3_ADMIN_ITEM_ID = "phase3-admin-final-approval"
DEFAULT_CHECKLIST = "artifacts/ai_ops_phase3_signoff_checklist.json"
DEFAULT_DRILL = "artifacts/ops_phase3_governance_drill.json"


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "UNRESOLVED"


def _default_checklist(repo_root: Path) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "checklistVersion": "phase3-v1",
        "generatedAt": now,
        "specReferences": [
            "docs/ai-ops-backoffice-phase-3-ai-governance-spec.md §21",
            "docs/ai-ops-phase-3-governance-handoff.md",
        ],
        "phase3ApprovalPolicy": {
            "policy": "SINGLE_APPROVER",
            "requiredApprover": "Justin",
            "authorityRole": "SYSTEM_ADMIN",
            "status": "pending",
            "approvedBy": "",
            "approvedAt": "",
            "notes": "",
        },
        "target": {
            "environment": "lab",
            "commitSha": _git_commit(repo_root),
        },
        "technicalEvidence": {
            "requiredArtifacts": [
                DEFAULT_DRILL,
                "docs/ai-ops-phase-3-governance-handoff.md",
            ]
        },
        "signOffItems": [
            {
                "id": PHASE3_ADMIN_ITEM_ID,
                "role": "SYSTEM_ADMIN",
                "description": (
                    "Give final Phase 3 milestone approval after reviewing "
                    "governance drill evidence and handoff"
                ),
                "status": "pending",
                "approvedBy": "",
                "approvedAt": "",
                "notes": "",
                "reviewArtifacts": [
                    DEFAULT_DRILL,
                    "docs/ai-ops-phase-3-governance-handoff.md",
                    "docs/ai-ops-backoffice-runbook.md",
                ],
            }
        ],
    }


def init_checklist(repo_root: Path, checklist_path: Path) -> dict[str, object]:
    payload = _default_checklist(repo_root)
    checklist_path.parent.mkdir(parents=True, exist_ok=True)
    checklist_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def approve(
    checklist_path: Path,
    *,
    approved_by: str,
    notes: str,
) -> dict[str, object]:
    payload = json.loads(checklist_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    items = payload.get("signOffItems")
    if not isinstance(items, list):
        raise ValueError("signOffItems must be a list")
    matched = False
    for item in items:
        if not isinstance(item, dict) or item.get("id") != PHASE3_ADMIN_ITEM_ID:
            continue
        item["status"] = "approved"
        item["approvedBy"] = approved_by
        item["approvedAt"] = now
        item["notes"] = notes
        matched = True
        break
    if not matched:
        raise ValueError(f"Missing sign-off item {PHASE3_ADMIN_ITEM_ID}")
    policy = payload.setdefault("phase3ApprovalPolicy", {})
    if not isinstance(policy, dict):
        raise ValueError("phase3ApprovalPolicy must be an object")
    policy["status"] = "approved"
    policy["approvedBy"] = approved_by
    policy["approvedAt"] = now
    policy["notes"] = notes
    policy["authorityRole"] = "SYSTEM_ADMIN"
    policy["policy"] = "SINGLE_APPROVER"
    payload["generatedAt"] = now
    checklist_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def validate(repo_root: Path, checklist_path: Path, drill_path: Path) -> list[str]:
    errors: list[str] = []
    if not checklist_path.is_file():
        return [f"checklist missing: {checklist_path}"]
    payload = json.loads(checklist_path.read_text(encoding="utf-8"))
    policy = payload.get("phase3ApprovalPolicy")
    if not isinstance(policy, dict):
        errors.append("phase3ApprovalPolicy is required")
    else:
        if policy.get("policy") != "SINGLE_APPROVER":
            errors.append("phase3ApprovalPolicy.policy must be SINGLE_APPROVER")
        if policy.get("authorityRole") != "SYSTEM_ADMIN":
            errors.append("phase3ApprovalPolicy.authorityRole must be SYSTEM_ADMIN")
        if policy.get("status") != "approved":
            errors.append("phase3ApprovalPolicy.status must be approved")
        if not str(policy.get("approvedBy") or "").strip():
            errors.append("phase3ApprovalPolicy.approvedBy is required")

    items = payload.get("signOffItems")
    if not isinstance(items, list):
        errors.append("signOffItems must be a list")
    else:
        indexed = {
            item.get("id"): item
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        item = indexed.get(PHASE3_ADMIN_ITEM_ID)
        if item is None:
            errors.append(f"Missing Phase 3 sign-off item: {PHASE3_ADMIN_ITEM_ID}")
        else:
            if item.get("role") != "SYSTEM_ADMIN":
                errors.append("Phase 3 final approval role must be SYSTEM_ADMIN")
            if item.get("status") != "approved":
                errors.append("Phase 3 admin sign-off item must be approved")

    if not drill_path.is_file():
        errors.append(f"drill report missing: {drill_path}")
    else:
        drill = json.loads(drill_path.read_text(encoding="utf-8"))
        if drill.get("passed") is not True:
            errors.append("Phase 3 governance drill report must have passed=true")
        if int(drill.get("failedCount") or 0) > 0:
            errors.append("Phase 3 governance drill still has failed steps")

    handoff = repo_root / "docs" / "ai-ops-phase-3-governance-handoff.md"
    if not handoff.is_file():
        errors.append("missing docs/ai-ops-phase-3-governance-handoff.md")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3 SYSTEM_ADMIN sign-off helper")
    parser.add_argument("command", choices=["init", "approve", "validate"])
    parser.add_argument("--checklist", default=DEFAULT_CHECKLIST)
    parser.add_argument("--drill", default=DEFAULT_DRILL)
    parser.add_argument("--by", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    checklist_path = Path(args.checklist)
    if not checklist_path.is_absolute():
        checklist_path = repo_root / checklist_path
    drill_path = Path(args.drill)
    if not drill_path.is_absolute():
        drill_path = repo_root / drill_path

    if args.command == "init":
        payload = init_checklist(repo_root, checklist_path)
        print(json.dumps({"checklist": str(checklist_path), "status": payload["phase3ApprovalPolicy"]["status"]}))
        return 0

    if args.command == "approve":
        if not args.by.strip():
            print("--by is required for approve", file=sys.stderr)
            return 1
        if not checklist_path.is_file():
            init_checklist(repo_root, checklist_path)
        approve(checklist_path, approved_by=args.by.strip(), notes=args.notes.strip())
        print(json.dumps({"approved": True, "checklist": str(checklist_path)}))
        return 0

    errors = validate(repo_root, checklist_path, drill_path)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"valid": True, "checklist": str(checklist_path), "drill": str(drill_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
