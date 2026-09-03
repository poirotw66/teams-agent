"""Build a reviewer evidence packet for formal AI Ops acceptance sign-off.

Usage:
    python scripts/ops_signoff_evidence.py
    python scripts/ops_signoff_evidence.py --report artifacts/ai_ops_signoff_evidence.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from ops_acceptance_evidence import UTC, formal_acceptance_errors, read_json, validate_acceptance_evidence, write_json


def _read_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    return read_json(path)


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
    evidence = report.get("acceptanceEvidence")
    return {
        "classification": evidence.get("classification") if isinstance(evidence, dict) else "LEGACY_UNCLASSIFIED",
        "technicalEvidenceErrors": validate_acceptance_evidence(evidence),
        "legacyReportedPassed": report.get("automatedVerificationPassed", report.get("passed")),
    }


def _terraform_summary(repo_root: Path) -> dict[str, object]:
    evidence = repo_root / "artifacts/terraform-ai-ops-plan-evidence.txt"
    if not evidence.is_file():
        return {"legacyCleanPatternFound": False, "detail": "missing plan evidence"}
    text = evidence.read_text(encoding="utf-8")
    return {
        "legacyCleanPatternFound": "No changes." in text,
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
                    "legacyReviewStatus": item.get("status"),
                    "approvedBy": item.get("approvedBy"),
                    "approvedAt": item.get("approvedAt"),
                    "trustStatus": "UNVERIFIED_LEGACY",
                    "artifactChecks": artifact_checks,
                }
            )

    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "specReferences": [
            "docs/ai-ops-backoffice-phase-0-foundation-spec.md §17",
            "docs/ai-ops-backoffice-phase-1-operations-mvp-spec.md §15",
        ],
        "uatHandoff": _uat_summary(repo_root),
        "terraform": _terraform_summary(repo_root),
        "signOffItems": sign_off_status,
        "formalAcceptanceErrors": formal_acceptance_errors(checklist, _read_json(repo_root / "artifacts/ai_ops_uat_acceptance_report.json") or {}),
        "nextSteps": [
            "Use this packet as LAB review material, not as formal approval evidence.",
            "Record formal approvals in the approved external authority system for the exact v2 target.",
            "Validate only with the executed v2 UAT report and a trusted read-only verifier.",
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

    packet = build_evidence_packet(repo_root)

    text = json.dumps(packet, indent=2, ensure_ascii=False)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
        print(f"Wrote sign-off evidence packet to {report_path}")
    else:
        print(text)

    print("Evidence packet generated; formal approval remains pending until trusted verification succeeds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
