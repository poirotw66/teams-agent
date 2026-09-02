#!/usr/bin/env python3
"""Build a reviewer evidence packet for formal AI Ops acceptance sign-off.

Usage:
    python scripts/ops_signoff_evidence.py
    python scripts/ops_signoff_evidence.py --report artifacts/ai_ops_signoff_evidence.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _read_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_artifact_path(repo_root: Path, reference: str) -> Path | None:
    file_reference = reference.split("::", 1)[0]
    candidates = [
        Path(file_reference),
        repo_root / file_reference,
        repo_root / "agent_service" / file_reference,
    ]
    if file_reference.startswith("tests/"):
        candidates.append(repo_root / "agent_service" / file_reference)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _artifact_exists(repo_root: Path, reference: str) -> bool:
    return _resolve_artifact_path(repo_root, reference) is not None


def _uat_summary(repo_root: Path) -> dict[str, object]:
    report = _read_json(repo_root / "artifacts/ai_ops_uat_acceptance_report.json") or {}
    steps = report.get("steps", [])
    failed_steps = [
        step.get("name")
        for step in steps
        if isinstance(step, dict) and step.get("exitCode") not in (0, None)
    ]
    return {
        "passed": bool(report.get("passed")),
        "generatedAt": report.get("generatedAt"),
        "failedSteps": failed_steps,
        "phase1CriteriaAutomated": all(
            item.get("status") == "automated"
            for item in report.get("phase1AcceptanceCriteria", [])
            if isinstance(item, dict)
        ),
    }


def _terraform_summary(repo_root: Path) -> dict[str, object]:
    evidence = repo_root / "artifacts/terraform-ai-ops-plan-evidence.txt"
    if not evidence.is_file():
        return {"planClean": False, "detail": "missing plan evidence"}
    text = evidence.read_text(encoding="utf-8")
    return {
        "planClean": "No changes." in text,
        "evidencePath": str(evidence),
    }


def build_evidence_packet(repo_root: Path) -> dict[str, object]:
    checklist_path = repo_root / "artifacts/ai_ops_signoff_checklist.json"
    checklist = _read_json(checklist_path) or {}
    items = checklist.get("signOffItems", [])

    sign_off_status: list[dict[str, object]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            review_artifacts = item.get("reviewArtifacts", [])
            artifact_checks: list[dict[str, object]] = []
            if isinstance(review_artifacts, list):
                for reference in review_artifacts:
                    ref = str(reference)
                    artifact_checks.append(
                        {
                            "reference": ref,
                            "exists": _artifact_exists(repo_root, ref),
                            "resolvedPath": str(resolved)
                            if (resolved := _resolve_artifact_path(repo_root, ref)) is not None
                            else None,
                        }
                    )
            sign_off_status.append(
                {
                    "id": item.get("id"),
                    "role": item.get("role"),
                    "status": item.get("status"),
                    "approvedBy": item.get("approvedBy"),
                    "approvedAt": item.get("approvedAt"),
                    "artifactChecks": artifact_checks,
                }
            )

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "specReferences": [
            "docs/ai-ops-backoffice-phase-0-foundation-spec.md §17",
            "docs/ai-ops-backoffice-phase-1-operations-mvp-spec.md §15",
        ],
        "uatHandoff": _uat_summary(repo_root),
        "terraform": _terraform_summary(repo_root),
        "signOffItems": sign_off_status,
        "nextSteps": [
            "Review each signOffItem artifactChecks list with the named role owner.",
            "Record approval: python scripts/ops_signoff_approve.py --item <id> --by \"Name\"",
            "Validate: python scripts/ops_signoff_checklist.py --validate artifacts/ai_ops_signoff_checklist.json",
            "Close: uv run python ../scripts/ops_uat_handoff.py --require-signoff (from agent_service)",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build AI Ops formal acceptance evidence packet.")
    parser.add_argument(
        "--report",
        default="",
        help="Optional path to write JSON evidence packet.",
    )
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    deliverables_exit = subprocess.run(
        [sys.executable, str(repo_root / "scripts/ops_deliverables_verify.py")],
        cwd=repo_root,
        check=False,
    ).returncode

    packet = build_evidence_packet(repo_root)
    packet["deliverablesVerifyPassed"] = deliverables_exit == 0

    text = json.dumps(packet, indent=2, ensure_ascii=False)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
        print(f"Wrote sign-off evidence packet to {report_path}")
    else:
        print(text)

    failed = 0
    if not packet["terraform"].get("planClean"):
        failed += 1
    if not packet["deliverablesVerifyPassed"]:
        failed += 1
    missing_artifacts = any(
        not check.get("exists")
        for item in packet["signOffItems"]
        for check in item.get("artifactChecks", [])
        if isinstance(check, dict)
    )
    if missing_artifacts:
        failed += 1
    pending = [
        item["id"]
        for item in packet["signOffItems"]
        if item.get("status") != "approved"
    ]
    if pending:
        print(f"\nPending manual sign-offs: {', '.join(str(item) for item in pending)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
