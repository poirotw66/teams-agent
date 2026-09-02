#!/usr/bin/env python3
"""Smoke test a deployed AI Ops Backoffice Cloud Run instance.

Validates that the live service responds to core read APIs with header auth.

Usage:
    python scripts/ops_live_smoke.py --base-url https://teams-ai-ops-backoffice-....run.app
    python scripts/ops_live_smoke.py --base-url ... --report artifacts/ops_live_smoke.json
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
class CheckResult:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def _request(
    base_url: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object] | None, str]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers=headers or {},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
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
        "X-Backoffice-User-Id": "uat.owner",
        "X-Backoffice-User-Name": "UAT Owner",
        "X-Backoffice-Role": "SERVICE_OWNER",
        "X-Backoffice-Owner-Units": "IT Service Desk",
    }


def _admin_headers() -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": "uat.admin",
        "X-Backoffice-User-Name": "UAT Admin",
        "X-Backoffice-Role": "SYSTEM_ADMIN",
        "X-Backoffice-Owner-Units": "IT Service Desk",
    }


def run_smoke(base_url: str) -> list[CheckResult]:
    results: list[CheckResult] = []

    status, _, detail = _request(base_url, "/")
    results.append(CheckResult("ui root responds", status == 200, f"status={status} {detail}".strip()))

    status, payload, detail = _request(base_url, "/api/capabilities", headers=_owner_headers())
    cap_count = len(payload.get("capabilities", [])) if payload else 0
    results.append(
        CheckResult(
            "capabilities endpoint",
            status == 200 and cap_count > 0,
            f"status={status} capabilities={cap_count} {detail}".strip(),
        )
    )

    status, payload, detail = _request(
        base_url,
        "/api/operations/summary?preset=7d",
        headers=_owner_headers(),
    )
    results.append(
        CheckResult(
            "operations summary",
            status == 200 and payload is not None and "conversationCount" in payload,
            f"status={status} {detail}".strip(),
        )
    )

    status, payload, detail = _request(
        base_url,
        "/api/health/summary",
        headers=_admin_headers(),
    )
    component_count = len(payload.get("components", [])) if payload else 0
    results.append(
        CheckResult(
            "health summary",
            status == 200 and component_count >= 3,
            f"status={status} components={component_count} {detail}".strip(),
        )
    )

    status, payload, detail = _request(
        base_url,
        "/api/metrics/definitions",
        headers=_owner_headers(),
    )
    definition_count = len(payload.get("definitions", [])) if payload else 0
    results.append(
        CheckResult(
            "metrics definitions",
            status == 200 and definition_count > 0,
            f"status={status} definitions={definition_count} {detail}".strip(),
        )
    )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test deployed AI Ops Backoffice.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    print(f"AI Ops live smoke test ({args.base_url})")
    checks = run_smoke(args.base_url)
    failed = 0
    for check in checks:
        marker = "PASS" if check.passed else "FAIL"
        suffix = f" -- {check.detail}" if check.detail else ""
        print(f"  [{marker}] {check.name}{suffix}")
        if not check.passed:
            failed += 1

    report = {
        "baseUrl": args.base_url,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "passed": failed == 0,
        "failureCount": failed,
        "checks": [check.to_dict() for check in checks],
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote live smoke report to {report_path}")

    print(f"\nCompleted with {failed} failure(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
