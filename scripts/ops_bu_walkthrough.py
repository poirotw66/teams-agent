#!/usr/bin/env python3
"""Automated BU acceptance walkthrough for AI Ops Backoffice Phase 1 §15.

Validates the scripted path: negative feedback -> conversation -> issue routes
-> source document performance. Intended to mirror the manual 15-minute UAT task.

Usage:
    python scripts/ops_bu_walkthrough.py \\
        --base-url https://teams-ai-ops-backoffice-....run.app
    python scripts/ops_bu_walkthrough.py --base-url ... --report artifacts/ops_bu_walkthrough.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class StepResult:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def _request(
    base_url: str,
    path: str,
    *,
    headers: dict[str, str],
) -> tuple[int, dict[str, object] | None, str]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return 0, None, str(exc.reason)

    if not body:
        return status, None, ""
    try:
        return status, json.loads(body), ""
    except json.JSONDecodeError:
        return status, None, body[:200]


def _owner_headers() -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": "bu.walkthrough",
        "X-Backoffice-User-Name": "BU Walkthrough",
        "X-Backoffice-Role": "SERVICE_OWNER",
        "X-Backoffice-Owner-Units": "IT Service Desk",
    }


def _knowledge_admin_headers() -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": "bu.knowledge",
        "X-Backoffice-User-Name": "BU Knowledge Admin",
        "X-Backoffice-Role": "KNOWLEDGE_ADMIN",
        "X-Backoffice-Owner-Units": "IT Service Desk",
    }


def run_walkthrough(base_url: str) -> list[StepResult]:
    headers = _owner_headers()
    steps: list[StepResult] = []

    status, payload, detail = _request(
        base_url,
        "/api/feedback?days=30&rating=DOWN",
        headers=headers,
    )
    items = payload.get("items", []) if payload else []
    if status != 200 or not items:
        steps.append(
            StepResult(
                "list negative feedback",
                False,
                f"status={status} items={len(items)} {detail}".strip(),
            )
        )
        return steps

    item = items[0]
    steps.append(
        StepResult(
            "list negative feedback",
            item.get("rating") == "DOWN" and bool(item.get("conversationId")),
            f"conversationId={item.get('conversationId')}",
        )
    )

    conversation_id = str(item["conversationId"])
    status, conversation, detail = _request(
        base_url,
        f"/api/conversations/{conversation_id}",
        headers=headers,
    )
    turns = conversation.get("turns", []) if conversation else []
    steps.append(
        StepResult(
            "open conversation detail",
            status == 200 and bool(turns),
            f"turns={len(turns)} {detail}".strip(),
        )
    )

    trace = item.get("trace") or {}
    issue_type_id = trace.get("issueTypeId")
    document_ids = trace.get("documentIds") or []
    steps.append(
        StepResult(
            "trace links issue and documents",
            bool(issue_type_id) and bool(document_ids),
            f"issue={issue_type_id} documents={document_ids}",
        )
    )
    if not issue_type_id or not document_ids:
        return steps

    status, routes_payload, detail = _request(
        base_url,
        f"/api/issues/{issue_type_id}/routes?days=30",
        headers=headers,
    )
    routes = routes_payload.get("routes", []) if routes_payload else []
    steps.append(
        StepResult(
            "drill into issue routes",
            status == 200 and bool(routes),
            f"routes={len(routes)} {detail}".strip(),
        )
    )

    document_id = str(document_ids[0])
    status, document_payload, detail = _request(
        base_url,
        f"/api/knowledge/{document_id}/performance?days=30",
        headers=_knowledge_admin_headers(),
    )
    hit_count = document_payload.get("hitCount", 0) if document_payload else 0
    governance_status = (document_payload.get("governance") or {}).get("status")
    steps.append(
        StepResult(
            "open source document performance",
            status == 200 and hit_count >= 1,
            f"hitCount={hit_count} governance={governance_status} {detail}".strip(),
        )
    )

    status, metrics_payload, detail = _request(
        base_url,
        "/api/metrics/definitions",
        headers=headers,
    )
    definitions = metrics_payload.get("definitions", []) if metrics_payload else []
    steps.append(
        StepResult(
            "KPI definitions available for drill-down",
            status == 200 and len(definitions) > 0,
            f"definitions={len(definitions)} {detail}".strip(),
        )
    )

    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BU acceptance walkthrough against live backoffice.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    print(f"AI Ops BU walkthrough ({args.base_url})")
    steps = run_walkthrough(args.base_url)
    failed = sum(1 for step in steps if not step.passed)
    for step in steps:
        marker = "PASS" if step.passed else "FAIL"
        suffix = f" -- {step.detail}" if step.detail else ""
        print(f"  [{marker}] {step.name}{suffix}")

    report = {
        "baseUrl": args.base_url,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "spec": "Phase 1 §15 BU acceptance task",
        "passed": failed == 0,
        "failureCount": failed,
        "steps": [step.to_dict() for step in steps],
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote BU walkthrough report to {report_path}")

    print(f"\nCompleted with {failed} failure(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
