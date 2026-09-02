#!/usr/bin/env python3
"""Verify AI Ops backup and recovery prerequisites for Phase 0 handoff.

Checks local Terraform artifacts and prints the operational recovery commands
operators should run in GCP. Does not mutate cloud resources.

Usage:
    python scripts/ops_backup_verify.py --project YOUR_PROJECT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _check_file(path: Path, label: str, results: list[tuple[str, bool, str]]) -> None:
    exists = path.is_file()
    results.append((label, exists, str(path)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AI Ops backup prerequisites.")
    parser.add_argument("--project", default="", help="GCP project ID for command examples.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    checks: list[tuple[str, bool, str]] = []

    _check_file(repo_root / "infra/terraform/ai_ops.tf", "terraform ai_ops", checks)
    _check_file(repo_root / "infra/terraform/ai_ops_monitoring.tf", "terraform monitoring", checks)
    _check_file(repo_root / "infra/terraform/ai_ops_logging.tf", "terraform logging sink", checks)
    _check_file(repo_root / "infra/ai-ops-environment-inventory.json", "environment inventory", checks)
    _check_file(repo_root / "scripts/ops_gcp_verification.py", "gcp verification script", checks)
    _check_file(repo_root / "scripts/ops_daily_reconciliation.py", "daily reconciliation", checks)
    _check_file(repo_root / "scripts/ops_replay_events.py", "event replay script", checks)
    _check_file(repo_root / "scripts/ops_live_smoke.py", "live smoke script", checks)
    _check_file(repo_root / "scripts/ops_bu_walkthrough.py", "bu walkthrough script", checks)
    _check_file(repo_root / "docs/ai-ops-backoffice-runbook.md", "operations runbook", checks)
    _check_file(repo_root / "scripts/ops_deliverables_verify.py", "phase0 deliverables verify", checks)

    failed = 0
    print("AI Ops backup/recovery prerequisite check")
    for label, passed, detail in checks:
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {label}: {detail}")
        if not passed:
            failed += 1

    project = args.project or "${PROJECT_ID}"
    print("\nRecovery runbook commands:")
    print(f"  gcloud firestore export gs://{project}-ops-backup/firestore --project={project}")
    print(f"  bq cp {project}:ai_ops_analytics.operational_events gs://{project}-ops-backup/bq/operational_events")
    print("  uv run --extra firestore --extra bigquery python scripts/ops_gcp_verification.py --project", project)
    print("  uv run python scripts/ops_daily_reconciliation.py --preset 30d")
    print("  uv run python scripts/ops_replay_events.py --input data/ops/sample_events.json")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
