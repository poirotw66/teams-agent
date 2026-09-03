"""Collect explicit LAB command observations, or inspect existing evidence read-only.

Default invocation only audits existing files. Collection requires --execute.
Outputs are new files; full-spec acceptance needs organisation verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from ops_acceptance_evidence import (
    UTC, LAB_SELF_TEST, LOCAL_SCOPE, REQUIRED_TECHNICAL_GATES, SPEC_CRITERIA,
    formal_acceptance_errors, manifest_sha256, protect_output, read_json,
    validate_acceptance_evidence, write_json,
)
from ops_formal_acceptance_audit import build_audit

PYTEST_TARGETS = (
    "tests/test_operations_phase0.py",
    "tests/test_operations_integrations.py",
    "tests/test_ai_ops_backoffice.py",
    "tests/test_ai_ops_backoffice_acceptance.py",
    "tests/test_ai_ops_backoffice_performance.py",
    "tests/test_ai_ops_portal_governance_integration.py",
    "tests/test_knowledge_portal.py::test_import_text_pdf",
    "tests/test_knowledge_portal.py::test_import_scanned_pdf_is_rejected",
    "tests/test_knowledge_portal.py::test_pdf_publish_workflow",
)


def _source_target(repo_root: Path, environment: str) -> dict:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.strip()
    names = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
         "agent_service", "scripts", "data", "infra", "docs"],
        cwd=repo_root, capture_output=True, check=True,
    ).stdout.decode().split("\0")
    hashes = {}
    for name in sorted(set(names)):
        if name:
            path = repo_root / name
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "DELETED"
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {
        "environment": environment, "commitSha": commit,
        "artifactIdentity": {"kind": "working-tree-sha256", "value": digest},
    }


def _run_step(
    gate_id: str, command: list[str], cwd: Path, target: dict, run_id: str,
    *, junit: Path | None = None, result_json: Path | None = None,
) -> dict:
    """Observe this command's exit, actual output and newly generated artifacts."""
    print(f"$ {shlex.join(command)}", file=sys.stderr)
    started = datetime.now(UTC)
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
        exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except OSError as exc:
        exit_code, stdout, stderr = 127, "", str(exc)
    passed = exit_code == 0
    result = {"summary": f"Observed command exit code {exit_code}", "stdout": stdout, "stderr": stderr}
    refs = [
        {"id": f"urn:uat:{run_id}:{gate_id}:{stream}", "sha256": hashlib.sha256(content.encode()).hexdigest()}
        for stream, content in (("stdout", stdout), ("stderr", stderr))
    ]
    if junit is not None:
        try:
            content = junit.read_text(encoding="utf-8")
            cases = list(ET.fromstring(content).iter("testcase"))
            skipped = sum(case.find("skipped") is not None for case in cases)
            failed = sum(case.find("failure") is not None or case.find("error") is not None for case in cases)
            passed = passed and bool(cases) and skipped == 0 and failed == 0
            result["tests"] = {"executed": len(cases), "skipped": skipped, "failed": failed}
            result["junit"] = content
            refs.append({"id": f"urn:uat:{run_id}:junit", "sha256": hashlib.sha256(content.encode()).hexdigest()})
        except (OSError, ET.ParseError):
            passed = False
            result["summary"] += "; no valid current JUnit results"
    if result_json is not None:
        try:
            content = result_json.read_text(encoding="utf-8")
            payload = read_json(result_json)
            passed = passed and payload.get("passed") is True
            result["report"] = payload
            refs.append({"id": f"urn:uat:{run_id}:{gate_id}:report", "sha256": hashlib.sha256(content.encode()).hexdigest()})
        except (OSError, TypeError, ValueError):
            passed = False
            result["summary"] += "; no valid current result report"
    return {
        "id": gate_id, "status": "PASSED" if passed else "FAILED",
        "command": shlex.join(command), "cwd": str(cwd), "exitCode": exit_code,
        "executedAt": started.isoformat(),
        "expiresAt": (started + timedelta(days=30)).isoformat(),
        "result": result, "artifactScope": {"target": target, "references": refs},
    }


def _write_acceptance_report(
    repo_root: Path, *, step_results: list[dict], gcp_report_path: Path | None = None,
    live_smoke_path: Path | None = None, bu_walkthrough_path: Path | None = None,
    terraform_plan_clean: bool | None = None, report_path: Path | None = None,
    target_environment: str = "lab", target: dict | None = None, run_id: str | None = None,
) -> dict:
    """Legacy call surface retained; bare exit codes cannot become valid evidence."""
    evidence = {
        "schemaVersion": "v2", "classification": LAB_SELF_TEST,
        "assessmentScope": LOCAL_SCOPE,
        "target": target if target is not None else _source_target(repo_root, target_environment),
        "runId": run_id or str(uuid.uuid4()),
        "expiresAt": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        "technicalEvidence": {
            "requiredGateIds": list(dict.fromkeys([*REQUIRED_TECHNICAL_GATES, *(
                step["id"] for step in step_results if isinstance(step, dict) and isinstance(step.get("id"), str)
            )])),
            "gates": step_results,
        },
    }
    evidence["technicalManifestSha256"] = manifest_sha256(evidence)
    errors = validate_acceptance_evidence(evidence)
    report = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "acceptanceEvidence": evidence,
        "observedCommandBundlePassed": not errors,
        "technicalSchemaErrors": errors,
        "evidenceTrust": "LOCAL_OBSERVATION_UNVERIFIED",
        "automatedVerificationPassed": False,
        "labSelfTestAccepted": False,
        "formalAcceptanceComplete": False,
        "formalApprovalStatus": "PENDING_ORGANISATION_VERIFICATION",
        "unassessedSpecCriteria": SPEC_CRITERIA,
    }
    if report_path is not None:
        write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect evidence; --execute collects a LAB command bundle.")
    parser.add_argument("--execute", action="store_true", help="Explicitly run tests and configured infrastructure checks.")
    parser.add_argument("--report", default="", help="New JSON output; omitted prints JSON without updating artifacts.")
    parser.add_argument("--uat-report", default="", help="Read-only UAT input for inspection.")
    parser.add_argument("--checklist", default="", help="Read-only formal checklist input.")
    parser.add_argument("--audit-report", default="", help="New audit JSON output.")
    parser.add_argument("--require-signoff", action="store_true")
    parser.add_argument("--target-environment", default="lab")
    parser.add_argument("--gcp-project", default="", help="With --execute, run existing GCP checks (may write test data).")
    parser.add_argument("--live-url", default="", help="With --execute, run existing deployed smoke/walkthrough checks.")
    parser.add_argument("--seed-lab-demo", action="store_true", help="Legacy flag; seeding is outside evidence collection.")
    parser.add_argument("--terraform-plan-evidence-report", default="", help="New path for current plan output.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        # Validate all output choices before commands can run.
        outputs = [Path(value) for value in (args.report, args.audit_report, args.terraform_plan_evidence_report) if value]
        if len({path.resolve() for path in outputs}) != len(outputs):
            raise ValueError("Output paths must be distinct")
        for path in outputs:
            protect_output(path)
        if args.seed_lab_demo:
            raise ValueError("Run explicitly authorized seeding separately; it is not an acceptance gate")
        if not args.execute and (args.gcp_project or args.live_url or args.terraform_plan_evidence_report):
            raise ValueError("Collection options require --execute")
        checklist = read_json(Path(args.checklist)) if args.checklist else None
        if not args.execute:
            audit = build_audit(
                repo_root, checklist=checklist,
                uat_report=read_json(Path(args.uat_report)) if args.uat_report else None,
            )
            if args.report:
                write_json(Path(args.report), audit)
            if args.audit_report:
                write_json(Path(args.audit_report), audit)
            print(json.dumps(audit, indent=2, ensure_ascii=False))
            return 1 if args.require_signoff and not audit["formalAcceptanceComplete"] else 0
        if args.uat_report:
            raise ValueError("--uat-report is for inspection; --execute uses only this run")
        target = _source_target(repo_root, args.target_environment)
        run_id = str(uuid.uuid4())
        agent_service = repo_root / "agent_service"
        with tempfile.TemporaryDirectory(prefix="ai-ops-uat-") as temporary:
            run_dir = Path(temporary)
            junit = run_dir / "pytest.xml"
            steps = [_run_step(
                "pytest", [sys.executable, "-m", "pytest", *PYTEST_TARGETS, "-q", f"--junitxml={junit}"],
                agent_service, target, run_id, junit=junit,
            )]
            commands = [
                ("backup_verify", [sys.executable, str(repo_root / "scripts/ops_backup_verify.py")], repo_root),
                ("phase0_deliverables", [sys.executable, str(repo_root / "scripts/ops_deliverables_verify.py")], repo_root),
                ("terraform_validate", ["terraform", "validate"], repo_root / "infra/terraform"),
                ("terraform_plan", ["terraform", "plan", "-detailed-exitcode", "-input=false", "-no-color"], repo_root / "infra/terraform"),
                ("daily_reconciliation", [sys.executable, str(repo_root / "scripts/ops_daily_reconciliation.py")], agent_service),
            ]
            for gate_id, command, cwd in commands:
                steps.append(_run_step(gate_id, command, cwd, target, run_id))
            if args.gcp_project:
                result_path = run_dir / "gcp.json"
                steps.append(_run_step(
                    "gcp_verification", [sys.executable, str(repo_root / "scripts/ops_gcp_verification.py"),
                                         "--project", args.gcp_project, "--report", str(result_path)],
                    agent_service, target, run_id, result_json=result_path,
                ))
            if args.live_url:
                for gate_id in ("live_smoke", "bu_walkthrough"):
                    result_path = run_dir / f"{gate_id}.json"
                    steps.append(_run_step(
                        gate_id, [sys.executable, str(repo_root / f"scripts/ops_{gate_id}.py"),
                                  "--base-url", args.live_url, "--report", str(result_path)],
                        repo_root, target, run_id, result_json=result_path,
                    ))
            if target != _source_target(repo_root, args.target_environment):
                for step in steps:
                    step["status"] = "INVALIDATED"
                    step["result"]["summary"] += "; source changed during execution"
            if args.terraform_plan_evidence_report:
                plan = next(step for step in steps if step["id"] == "terraform_plan")
                plan_path = Path(args.terraform_plan_evidence_report)
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                with plan_path.open("x", encoding="utf-8") as handle:
                    handle.write(plan["result"]["stdout"] + plan["result"]["stderr"])
            report = _write_acceptance_report(
                repo_root, step_results=steps, target=target, run_id=run_id,
                report_path=Path(args.report) if args.report else None,
            )
        audit = build_audit(repo_root, uat_report=report, checklist=checklist)
        if args.audit_report:
            write_json(Path(args.audit_report), audit)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if args.require_signoff:
            return 1 if formal_acceptance_errors(checklist or {}, report) else 0
        return 0 if report["observedCommandBundlePassed"] else 1
    except (OSError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Acceptance evidence failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
