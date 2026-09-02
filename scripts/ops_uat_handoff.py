#!/usr/bin/env python3
"""Run the AI Ops Backoffice UAT handoff verification bundle.

Executes automated tests, backup prerequisite checks, optional GCP live
verification, and reconciliation against the configured local ops store.

Usage:
    cd agent_service
    uv run python ../scripts/ops_uat_handoff.py
    uv run python ../scripts/ops_uat_handoff.py --gcp-project itr-aimasteryhub-lab
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _run(command: list[str], cwd: Path) -> int:
    print(f"\n$ {' '.join(command)}")
    completed = subprocess.run(command, cwd=cwd, check=False)
    return completed.returncode


def _uv_gcp_python(script_path: Path) -> list[str]:
    """Run an ops script with Firestore/BigQuery optional deps installed."""
    return [
        "uv",
        "run",
        "--extra",
        "firestore",
        "--extra",
        "bigquery",
        "python",
        str(script_path),
    ]


def _terraform_plan_is_clean(repo_root: Path) -> tuple[int, Path]:
    terraform_dir = repo_root / "infra" / "terraform"
    evidence_path = repo_root / "artifacts" / "terraform-ai-ops-plan-evidence.txt"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["terraform", "plan", "-input=false", "-no-color"],
        cwd=terraform_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    output = completed.stdout + completed.stderr
    evidence_path.write_text(output, encoding="utf-8")
    clean = "No changes." in output and completed.returncode == 0
    return (0 if clean else 1), evidence_path


def _signoff_status(repo_root: Path) -> dict[str, object]:
    checklist_path = repo_root / "artifacts" / "ai_ops_signoff_checklist.json"
    if not checklist_path.is_file():
        return {"complete": False, "approved": [], "pending": ["all"]}
    payload = json.loads(checklist_path.read_text(encoding="utf-8"))
    items = payload.get("signOffItems", [])
    if not isinstance(items, list):
        return {"complete": False, "approved": [], "pending": ["invalid-checklist"]}
    approved = [str(item.get("id")) for item in items if item.get("status") == "approved"]
    pending = [
        str(item.get("id"))
        for item in items
        if isinstance(item, dict) and item.get("status") != "approved"
    ]
    return {"complete": len(pending) == 0, "approved": approved, "pending": pending}


def _write_acceptance_report(
    repo_root: Path,
    *,
    step_results: list[dict[str, object]],
    gcp_report_path: Path | None,
    live_smoke_path: Path | None = None,
    bu_walkthrough_path: Path | None = None,
    terraform_plan_clean: bool | None = None,
) -> Path:
    artifacts = repo_root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    report_path = artifacts / "ai_ops_uat_acceptance_report.json"
    gcp_payload: dict[str, object] | None = None
    gcp_step = next((step for step in step_results if step.get("name") == "gcp_verification"), None)
    if (
        gcp_report_path is not None
        and gcp_report_path.is_file()
        and gcp_step is not None
        and gcp_step.get("exitCode") == 0
    ):
        gcp_payload = json.loads(gcp_report_path.read_text(encoding="utf-8"))
    live_smoke_payload: dict[str, object] | None = None
    if live_smoke_path is not None and live_smoke_path.is_file():
        live_smoke_payload = json.loads(live_smoke_path.read_text(encoding="utf-8"))

    bu_walkthrough_payload: dict[str, object] | None = None
    if bu_walkthrough_path is not None and bu_walkthrough_path.is_file():
        bu_walkthrough_payload = json.loads(bu_walkthrough_path.read_text(encoding="utf-8"))

    automated_checks = [
        {
            "id": "phase0-deliverables",
            "spec": "Phase 0 §15",
            "evidence": "scripts/ops_deliverables_verify.py",
        },
        {
            "id": "phase0-event-idempotency",
            "spec": "Phase 0 §14.2",
            "evidence": "tests/test_operations_phase0.py",
        },
        {
            "id": "phase0-masked-export-fail-closed",
            "spec": "Phase 0 §10",
            "evidence": "tests/test_ai_ops_backoffice.py::test_export_audit_fail_closed",
        },
        {
            "id": "phase0-retention-purge",
            "spec": "Phase 0 §14.8",
            "evidence": "tests/test_operations_phase0.py::test_purge_expired_events_removes_only_expired_records",
        },
        {
            "id": "phase1-negative-feedback-drill-down",
            "spec": "Phase 1 §12.10 / §15",
            "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_negative_feedback_drill_down_path",
        },
        {
            "id": "phase1-unmask-step-up",
            "spec": "Phase 1 §10",
            "evidence": "tests/test_ai_ops_backoffice.py::test_conversation_unmask_requires_capability_and_reason",
        },
        {
            "id": "phase1-reconciliation",
            "spec": "Phase 1 §15",
            "evidence": "scripts/ops_daily_reconciliation.py",
        },
        {
            "id": "phase1-document-governance-proxy",
            "spec": "Phase 1 §12.7",
            "evidence": (
                "tests/test_ai_ops_backoffice_acceptance.py::test_uat_document_governance_markdown_from_portal"
            ),
        },
        {
            "id": "phase1-bu-walkthrough",
            "spec": "Phase 1 §15",
            "evidence": "scripts/ops_bu_walkthrough.py",
        },
        {
            "id": "phase1-live-deployment-smoke",
            "spec": "Phase 1 §11 / LAB handoff",
            "evidence": "scripts/ops_live_smoke.py",
        },
        {
            "id": "phase0-terraform-zero-diff",
            "spec": "Phase 0 §17",
            "evidence": "artifacts/terraform-ai-ops-plan-evidence.txt",
        },
        {
            "id": "phase1-monitoring-runbook",
            "spec": "Phase 1 §15",
            "evidence": "docs/ai-ops-backoffice-runbook.md",
        },
        {
            "id": "phase1-portal-governance-e2e",
            "spec": "Phase 1 §12.7",
            "evidence": (
                "tests/test_ai_ops_portal_governance_integration.py::"
                "test_portal_publish_surfaces_in_backoffice_governance"
            ),
        },
    ]
    manual_sign_off = [
        "BU approval of issue taxonomy v1 and metric definitions",
        "IT approval of Terraform apply in target environment",
        "Security/legal approval of masking, retention, and export policy",
        "Markdown/PDF knowledge governance end-to-end UAT in Knowledge Portal",
    ]
    phase1_acceptance_criteria = [
        {
            "id": "12.1",
            "description": "Conversation counts reconcile with deduplicated raw events",
            "status": "automated",
            "evidence": "scripts/ops_daily_reconciliation.py",
        },
        {
            "id": "12.2",
            "description": "Model token/cost traceable to pricing version; unknown price not shown as zero",
            "status": "automated",
            "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_missing_cost_not_counted_as_zero",
        },
        {
            "id": "12.3",
            "description": "Authorized actor lookup within six months; unauthorized users masked or 403",
            "status": "automated",
            "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_actor_ref_conversation_lookup",
        },
        {
            "id": "12.4",
            "description": "Conversation traceability to issue, route, documents, feedback, handoff",
            "status": "automated",
            "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_negative_feedback_drill_down_path",
        },
        {
            "id": "12.5",
            "description": "Issue dashboard supports day/week/month/six-month/custom periods",
            "status": "automated",
            "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_period_presets_supported",
        },
        {
            "id": "12.6",
            "description": "Document page shows hits, feedback, issues, and conversations",
            "status": "automated",
            "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_negative_feedback_drill_down_path",
        },
        {
            "id": "12.7",
            "description": "Markdown/PDF governance publish and index status E2E",
            "status": "automated",
            "evidence": (
                "tests/test_ai_ops_portal_governance_integration.py::test_portal_publish_surfaces_in_backoffice_governance; "
                "tests/test_ai_ops_portal_governance_integration.py::test_portal_pdf_publish_surfaces_in_backoffice_governance; "
                "tests/test_knowledge_portal.py::test_pdf_publish_workflow"
            ),
        },
        {
            "id": "12.8",
            "description": "Health summary detects simulated LLM/RAG/Ticket anomalies",
            "status": "automated",
            "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_health_detects_simulated_anomalies",
        },
        {
            "id": "12.9",
            "description": "Exports enforce same permissions/masking and write audit events",
            "status": "automated",
            "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_export_records_audit_and_metadata",
        },
        {
            "id": "12.10",
            "description": "Dashboard KPIs drill down or link to metric definitions",
            "status": "automated",
            "evidence": "tests/test_ai_ops_backoffice_acceptance.py::test_uat_negative_feedback_drill_down_path",
        },
    ]
    terraform_plan_evidence = repo_root / "artifacts" / "terraform-ai-ops-plan-evidence.txt"
    signoff_status = _signoff_status(repo_root)
    automated_steps = [
        step for step in step_results if step.get("name") != "signoff_validation"
    ]
    automated_verification_passed = all(step["exitCode"] == 0 for step in automated_steps)
    signoff_validation = next(
        (step for step in step_results if step.get("name") == "signoff_validation"),
        None,
    )
    formal_acceptance_complete = bool(signoff_status["complete"])
    if signoff_validation is not None:
        formal_acceptance_complete = signoff_validation.get("exitCode") == 0

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "passed": all(step["exitCode"] == 0 for step in step_results),
        "automatedVerificationPassed": automated_verification_passed,
        "formalAcceptanceComplete": formal_acceptance_complete,
        "signOffStatus": signoff_status,
        "automatedChecks": automated_checks,
        "phase1AcceptanceCriteria": phase1_acceptance_criteria,
        "manualSignOffRequired": manual_sign_off,
        "infrastructureEvidence": {
            "terraformValidate": any(
                step.get("name") == "terraform_validate" and step.get("exitCode") == 0
                for step in step_results
            ),
            "terraformPlanClean": terraform_plan_clean,
            "terraformPlanEvidence": str(terraform_plan_evidence)
            if terraform_plan_evidence.is_file()
            else None,
            "gcpVerificationReport": str(gcp_report_path) if gcp_report_path else None,
            "liveSmokeReport": str(live_smoke_path) if live_smoke_path else None,
            "buWalkthroughReport": str(bu_walkthrough_path) if bu_walkthrough_path else None,
        },
        "steps": step_results,
        "gcpVerification": gcp_payload,
        "liveSmoke": live_smoke_payload,
        "buWalkthrough": bu_walkthrough_payload,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote UAT acceptance report to {report_path}")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI Ops UAT handoff verification.")
    parser.add_argument("--gcp-project", default="", help="Optional GCP project for live verification.")
    parser.add_argument(
        "--live-url",
        default="",
        help="Optional deployed backoffice base URL for live smoke checks.",
    )
    parser.add_argument(
        "--seed-lab-demo",
        action="store_true",
        help="Seed LAB Firestore demo events before verification (requires --gcp-project).",
    )
    parser.add_argument(
        "--require-signoff",
        action="store_true",
        help="Fail when manual sign-off checklist items are not all approved.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    agent_service = repo_root / "agent_service"
    step_results: list[dict[str, object]] = []
    gcp_report_path: Path | None = None

    print("AI Ops Backoffice UAT handoff verification")

    if args.seed_lab_demo:
        if not args.gcp_project:
            print("--seed-lab-demo requires --gcp-project", file=sys.stderr)
            return 1
        seed_exit = _run(
            [
                *_uv_gcp_python(repo_root / "scripts" / "ops_seed_lab_demo.py"),
                "--project",
                args.gcp_project,
            ],
            agent_service,
        )
        step_results.append({"name": "lab_demo_seed", "exitCode": seed_exit, "project": args.gcp_project})

    pytest_exit = _run(
        [
            "uv",
            "run",
            "pytest",
            "tests/test_operations_phase0.py",
            "tests/test_operations_integrations.py",
            "tests/test_ai_ops_backoffice.py",
            "tests/test_ai_ops_backoffice_acceptance.py",
            "tests/test_ai_ops_backoffice_performance.py",
            "tests/test_ai_ops_portal_governance_integration.py",
            "tests/test_knowledge_portal.py::test_import_text_pdf",
            "tests/test_knowledge_portal.py::test_import_scanned_pdf_is_rejected",
            "tests/test_knowledge_portal.py::test_pdf_publish_workflow",
            "-q",
        ],
        agent_service,
    )
    step_results.append({"name": "pytest", "exitCode": pytest_exit})

    backup_exit = _run(["python3", str(repo_root / "scripts" / "ops_backup_verify.py")], repo_root)
    step_results.append({"name": "backup_verify", "exitCode": backup_exit})

    deliverables_exit = _run(
        ["python3", str(repo_root / "scripts" / "ops_deliverables_verify.py")],
        repo_root,
    )
    step_results.append({"name": "phase0_deliverables", "exitCode": deliverables_exit})

    terraform_exit = _run(["terraform", "validate"], repo_root / "infra" / "terraform")
    step_results.append({"name": "terraform_validate", "exitCode": terraform_exit})

    terraform_plan_exit, _ = _terraform_plan_is_clean(repo_root)
    step_results.append({"name": "terraform_plan", "exitCode": terraform_plan_exit})

    gcp_exit = 0
    if args.gcp_project:
        gcp_report_path = repo_root / "artifacts" / "ai_ops_gcp_verification.json"
        gcp_exit = _run(
            [
                *_uv_gcp_python(repo_root / "scripts" / "ops_gcp_verification.py"),
                "--project",
                args.gcp_project,
                "--report",
                str(gcp_report_path),
            ],
            agent_service,
        )
        step_results.append({"name": "gcp_verification", "exitCode": gcp_exit, "project": args.gcp_project})

    reconciliation_exit = _run(
        ["uv", "run", "python", str(repo_root / "scripts" / "ops_daily_reconciliation.py")],
        agent_service,
    )
    step_results.append({"name": "daily_reconciliation", "exitCode": reconciliation_exit})

    live_smoke_path: Path | None = None
    bu_walkthrough_path: Path | None = None
    live_smoke_exit = 0
    if args.live_url:
        live_smoke_path = repo_root / "artifacts" / "ops_live_smoke.json"
        live_smoke_exit = _run(
            [
                "python3",
                str(repo_root / "scripts" / "ops_live_smoke.py"),
                "--base-url",
                args.live_url,
                "--report",
                str(live_smoke_path),
            ],
            repo_root,
        )
        step_results.append({"name": "live_smoke", "exitCode": live_smoke_exit, "url": args.live_url})

        bu_walkthrough_path = repo_root / "artifacts" / "ops_bu_walkthrough.json"
        bu_walkthrough_exit = _run(
            [
                "python3",
                str(repo_root / "scripts" / "ops_bu_walkthrough.py"),
                "--base-url",
                args.live_url,
                "--report",
                str(bu_walkthrough_path),
            ],
            repo_root,
        )
        step_results.append(
            {"name": "bu_walkthrough", "exitCode": bu_walkthrough_exit, "url": args.live_url}
        )

    signoff_path = repo_root / "artifacts" / "ai_ops_signoff_checklist.json"
    signoff_write_exit = _run(
        [
            "python3",
            str(repo_root / "scripts" / "ops_signoff_checklist.py"),
            "--sync",
            str(signoff_path),
        ],
        repo_root,
    )
    step_results.append({"name": "signoff_checklist", "exitCode": signoff_write_exit})

    evidence_path = repo_root / "artifacts" / "ai_ops_signoff_evidence.json"
    signoff_evidence_exit = _run(
        [
            "python3",
            str(repo_root / "scripts" / "ops_signoff_evidence.py"),
            "--report",
            str(evidence_path),
        ],
        repo_root,
    )
    step_results.append({"name": "signoff_evidence", "exitCode": signoff_evidence_exit})

    signoff_validate_exit = 0
    if args.require_signoff:
        signoff_validate_exit = _run(
            [
                "python3",
                str(repo_root / "scripts" / "ops_signoff_checklist.py"),
                "--validate",
                str(signoff_path),
            ],
            repo_root,
        )
        step_results.append({"name": "signoff_validation", "exitCode": signoff_validate_exit})

    _write_acceptance_report(
        repo_root,
        step_results=step_results,
        gcp_report_path=gcp_report_path,
        live_smoke_path=live_smoke_path,
        bu_walkthrough_path=bu_walkthrough_path,
        terraform_plan_clean=terraform_plan_exit == 0,
    )

    audit_path = repo_root / "artifacts" / "ai_ops_formal_acceptance_audit.json"
    audit_exit = _run(
        [
            "python3",
            str(repo_root / "scripts" / "ops_formal_acceptance_audit.py"),
            "--report",
            str(audit_path),
        ],
        repo_root,
    )
    step_results.append({"name": "formal_acceptance_audit", "exitCode": audit_exit})
    _write_acceptance_report(
        repo_root,
        step_results=step_results,
        gcp_report_path=gcp_report_path,
        live_smoke_path=live_smoke_path,
        bu_walkthrough_path=bu_walkthrough_path,
        terraform_plan_clean=terraform_plan_exit == 0,
    )

    failures = sum(step["exitCode"] for step in step_results if step["exitCode"] != 0)

    if failures:
        print(f"\nUAT handoff verification failed with {failures} step(s).", file=sys.stderr)
        return 1
    print("\nUAT handoff verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
