"""Create or validate the fail-closed Phase 0/1 acceptance checklist.

``--sync`` is an explicit migration action. It retains legacy review fields
outside the v2 formal-approval fields, where they cannot satisfy formal gates.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from ops_acceptance_evidence import (
    UTC,
    FORMAL_ACCEPTANCE,
    PHASE01_SCOPE,
    REQUIRED_PHASE01_GATES,
    REQUIRED_REVIEWER_ROLES,
    manifest_sha256,
    protect_output,
    read_json,
    write_json,
    formal_acceptance_errors,
)


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else "UNRESOLVED"


def _target(repo_root: Path, environment: str) -> dict[str, object]:
    commit_sha = _git_commit(repo_root)
    return {
        "environment": environment,
        "commitSha": commit_sha,
        "artifactIdentity": {"kind": "git-commit", "value": commit_sha},
    }


def _default_checklist(repo_root: Path, environment: str = "lab") -> dict[str, object]:
    now = datetime.now(UTC)
    expires = (now + timedelta(days=30)).isoformat()
    target = _target(repo_root, environment)
    gates = [
        {
            "id": gate_id,
            "status": "NOT_RUN",
            "command": "",
            "cwd": "",
            "exitCode": None,
            "executedAt": "",
            "expiresAt": expires,
            "result": {"summary": "Pending execution"},
            "artifactScope": {"target": target, "references": []},
        }
        for gate_id in REQUIRED_PHASE01_GATES
    ]
    approvals = [
        {
            "role": role,
            "decisionId": "",
            "assessmentScope": PHASE01_SCOPE,
            "reviewedManifestSha256": "",
            "status": "PENDING",
            "reviewer": {"subjectId": "", "displayName": ""},
            "approvedAt": "",
            "expiresAt": expires,
            "reviewedTarget": target,
            "authorityEvidence": {
                "sourceSystem": "",
                "sourceRecordId": "",
                "verificationStatus": "PENDING_HUMAN",
                "verifiedAt": "",
            },
        }
        for role in REQUIRED_REVIEWER_ROLES
    ]
    payload = {
        "checklistVersion": "v2",
        "generatedAt": now.isoformat(),
        "specReferences": [
            "docs/ai-ops-backoffice-phase-0-foundation-spec.md §14, §17",
            "docs/ai-ops-backoffice-phase-1-operations-mvp-spec.md §12, §15",
        ],
        "acceptanceEvidence": {
            "schemaVersion": "v2",
            "classification": FORMAL_ACCEPTANCE,
            "assessmentScope": PHASE01_SCOPE,
            "runId": "",
            "target": target,
            "expiresAt": expires,
            "technicalEvidence": {"requiredGateIds": list(REQUIRED_PHASE01_GATES), "gates": gates},
            "requiredReviewerRoles": list(REQUIRED_REVIEWER_ROLES),
            "formalApprovals": approvals,
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
                "reviewArtifacts": ["data/ops/issue_taxonomy_v1.json", "data/ops/metrics_definitions_v1.json"],
            },
            {
                "id": "it-terraform",
                "role": "IT",
                "description": "Approve Terraform state and target-environment plan",
                "status": "pending",
                "approvedBy": "",
                "approvedAt": "",
                "notes": "",
                "reviewArtifacts": ["infra/terraform/INVENTORY.md", "artifacts/terraform-ai-ops-plan-evidence.txt"],
            },
            {
                "id": "security-masking-retention",
                "role": "Security/Legal",
                "description": "Approve masking, retention, export, and audit policy",
                "status": "pending",
                "approvedBy": "",
                "approvedAt": "",
                "notes": "",
                "reviewArtifacts": ["data/ops/data_governance_decisions_v1.json", "data/ops/role_capability_matrix_v1.json"],
            },
            {
                "id": "knowledge-portal-governance",
                "role": "BU/Knowledge Admin",
                "description": "Complete Markdown/PDF publish UAT in the target portal",
                "status": "pending",
                "approvedBy": "",
                "approvedAt": "",
                "notes": "",
                "reviewArtifacts": ["agent_service/tests/test_ai_ops_portal_governance_integration.py"],
            },
        ],
    }
    payload["acceptanceEvidence"]["technicalManifestSha256"] = manifest_sha256(payload["acceptanceEvidence"])
    return payload


def sync_checklist(repo_root: Path, source: Path, environment: str = "lab") -> dict[str, object]:
    """Return a v2 draft while retaining legacy records outside formal approvals."""
    existing: dict[str, object] = {}
    if source.is_file():
        existing = _read_json(source)
    payload = _default_checklist(repo_root, environment)
    if "acceptanceEvidence" in existing:
        payload["previousAcceptanceEvidence"] = existing["acceptanceEvidence"]
    legacy_items = existing.get("signOffItems")
    if isinstance(legacy_items, list):
        payload["signOffItems"] = legacy_items
        payload["legacyApprovalRecords"] = [
            {**item, "trustStatus": "UNVERIFIED_LEGACY"}
            for item in legacy_items
            if isinstance(item, dict) and item.get("status") == "approved"
        ]
    payload["migrationNote"] = (
        "Legacy status/approvedBy/notes were not promoted. Re-record formal approvals with "
        "external authority evidence for this exact target."
    )
    return payload


def _validate_checklist(payload: dict[str, object], uat_report: dict[str, object] | None = None) -> list[str]:
    return formal_acceptance_errors(payload, uat_report or {})


def _read_json(path: Path) -> dict[str, object]:
    return read_json(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage fail-closed AI Ops formal acceptance evidence.")
    parser.add_argument("--write", default="", help="Write a new pending v2 checklist to this path.")
    parser.add_argument("--sync", default="", help="Read a legacy/current checklist and create a new pending v2 draft.")
    parser.add_argument("--output", default="", help="Optional new output path for --sync; omitted explicitly syncs the named local checklist in place.")
    parser.add_argument("--validate", default="", help="Read and validate a v2 formal checklist.")
    parser.add_argument("--uat-report", default="", help="Executed v2 LAB self-test report bound to formal evidence.")
    parser.add_argument("--environment", default="lab", help="Target environment for a new template.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    if args.write:
        path = Path(args.write)
        try:
            write_json(path, _default_checklist(repo_root, args.environment))
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Wrote pending v2 sign-off checklist to {path}")
        return 0
    if args.sync:
        source = Path(args.sync)
        output = Path(args.output) if args.output else source
        try:
            protect_output(output, allow_local_update=output.resolve() == source.resolve())
            payload = sync_checklist(repo_root, source, args.environment)
            write_json(output, payload, allow_local_update=output.resolve() == source.resolve())
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"Cannot sync checklist: {exc}", file=sys.stderr)
            return 1

        print(f"Synced v2 checklist to {output}; retained approvals are unverified legacy records only")
        return 0
    if args.validate:
        path = Path(args.validate)
        if not path.is_file():
            print(f"Checklist not found: {path}", file=sys.stderr)
            return 1
        try:
            uat = _read_json(Path(args.uat_report)) if args.uat_report else {}
            errors = _validate_checklist(_read_json(path), uat)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"Cannot validate checklist: {exc}", file=sys.stderr)
            return 1
        if errors:
            for error in errors:
                print(f"  [FAIL] {error}")
            return 1
        print("Formal acceptance evidence validation passed.")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
