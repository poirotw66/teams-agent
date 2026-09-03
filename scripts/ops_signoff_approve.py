#!/usr/bin/env python3
"""Record a local review marker; this never creates a formal approval.

Usage:
    python scripts/ops_signoff_approve.py \\
        --checklist artifacts/ai_ops_signoff_checklist.json \\
        --item bu-taxonomy-metrics \\
        --by "Service Owner Name" \\
        --notes "Reviewed taxonomy v1 and metrics definitions on LAB."
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ops_acceptance_evidence import read_json, write_json


def approve_item(
    checklist_path: Path,
    *,
    item_id: str,
    approved_by: str,
    approved_at: str,
    notes: str,
) -> dict[str, object]:
    payload = read_json(checklist_path)
    items = payload.get("signOffItems")
    if not isinstance(items, list):
        raise ValueError("signOffItems must be a list")

    matched = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("id") != item_id:
            continue
        item["status"] = "approved"
        item["approvedBy"] = approved_by
        item["approvedAt"] = approved_at
        if notes:
            item["notes"] = notes
        matched = True
        break

    if not matched:
        known = [str(item.get("id")) for item in items if isinstance(item, dict)]
        raise ValueError(f"Unknown sign-off item '{item_id}'. Known items: {', '.join(known)}")

    payload["generatedAt"] = datetime.now(timezone.utc).isoformat()
    write_json(checklist_path, payload, allow_local_update=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Record an unverified local AI Ops review marker.")
    parser.add_argument("--checklist", required=True, help="Path to sign-off checklist JSON.")
    parser.add_argument("--item", required=True, help="Sign-off item id to approve.")
    parser.add_argument("--by", required=True, help="Approver display name or email.")
    parser.add_argument(
        "--at",
        default="",
        help="Approval timestamp in ISO-8601 (defaults to current UTC time).",
    )
    parser.add_argument("--notes", default="", help="Optional approval notes.")
    args = parser.parse_args()

    checklist_path = Path(args.checklist)
    if not checklist_path.is_file():
        print(f"Checklist not found: {checklist_path}", file=sys.stderr)
        return 1

    approved_at = args.at.strip() or datetime.now(timezone.utc).isoformat()
    try:
        approve_item(
            checklist_path,
            item_id=args.item,
            approved_by=args.by.strip(),
            approved_at=approved_at,
            notes=args.notes.strip(),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Recorded unverified local review '{args.item}' for {args.by.strip()}; not formal approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
