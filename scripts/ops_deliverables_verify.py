#!/usr/bin/env python3
"""Verify Phase 0 data deliverables required for formal handoff."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    ops_dir = repo_root / "data" / "ops"
    checks: list[tuple[str, bool, str]] = []

    required_files = [
        "issue_taxonomy_v1.json",
        "issue_classification_rules.json",
        "metrics_definitions_v1.json",
        "sample_events.json",
        "operational_event_schema_v1.json",
        "role_capability_matrix_v1.json",
        "data_governance_decisions_v1.json",
    ]
    for name in required_files:
        path = ops_dir / name
        checks.append((f"deliverable {name}", path.is_file(), str(path)))

    taxonomy = _load_json(ops_dir / "issue_taxonomy_v1.json")
    issue_types = taxonomy.get("issue_types", [])
    active_leaf_count = sum(
        1
        for item in issue_types
        if item.get("status") == "ACTIVE" and item.get("issue_type_id") != "other.unclassified"
    )
    checks.append(
        (
            "taxonomy has 20-50 active issue types",
            20 <= active_leaf_count <= 50,
            f"count={active_leaf_count}",
        )
    )
    checks.append(
        (
            "taxonomy includes other.unclassified",
            any(item.get("issue_type_id") == "other.unclassified" for item in issue_types),
            "",
        )
    )

    schema = _load_json(ops_dir / "operational_event_schema_v1.json")
    checks.append(
        (
            "event schema defines envelope fields",
            len(schema.get("envelopeFields", [])) >= 10,
            f"fields={len(schema.get('envelopeFields', []))}",
        )
    )

    matrix = _load_json(ops_dir / "role_capability_matrix_v1.json")
    checks.append(
        (
            "role capability matrix defines six roles",
            len(matrix.get("roles", [])) == 6,
            f"roles={len(matrix.get('roles', []))}",
        )
    )

    governance = _load_json(ops_dir / "data_governance_decisions_v1.json")
    checks.append(
        (
            "governance decisions document retention",
            governance.get("retention", {}).get("operationalEventsDays") == 365,
            "",
        )
    )

    failed = 0
    print("AI Ops Phase 0 deliverables verification")
    for label, passed, detail in checks:
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {label}{f' -- {detail}' if detail else ''}")
        if not passed:
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
