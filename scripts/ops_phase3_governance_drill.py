#!/usr/bin/env python3
"""Phase 3 governance LAB drill: prompt/flag/retention/masking/roles + audit export.

Default mode uses an in-process FastAPI TestClient (no live server required).

Usage:
    cd agent_service
    uv run python ../scripts/ops_phase3_governance_drill.py
    uv run python ../scripts/ops_phase3_governance_drill.py \\
        --report ../artifacts/ops_phase3_governance_drill.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
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


def _headers(role: str, user_id: str) -> dict[str, str]:
    return {
        "X-Backoffice-User-Id": user_id,
        "X-Backoffice-User-Name": role,
        "X-Backoffice-Role": role,
        "X-Backoffice-Owner-Units": "IT Service Desk",
    }


def _run_inprocess(report_path: Path) -> dict[str, object]:
    from fastapi.testclient import TestClient

    from ai_ops_backoffice.api import create_app
    from ai_ops_backoffice.settings import BackofficeSettings

    data_dir = Path(__file__).resolve().parents[1] / "data"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = BackofficeSettings(
            host="127.0.0.1",
            port=8092,
            service_token="",
            auth_mode="HEADER",
            ops_store_mode="MEMORY",
            ops_store_path=tmp_path / "events",
            ops_taxonomy_path=data_dir / "ops" / "issue_taxonomy_v1.json",
            ops_metrics_path=data_dir / "ops" / "metrics_definitions_v1.json",
            ops_classification_rules_path=data_dir / "ops" / "issue_classification_rules.json",
            ops_audit_store_mode="FILE",
            knowledge_portal_url="http://127.0.0.1:8091",
            agent_api_url="http://127.0.0.1:8000",
            adapter_api_url="http://127.0.0.1:3978",
            ticket_service_url=None,
            default_owner_unit_id="IT Service Desk",
            entra_tenant_id=None,
            entra_client_id=None,
            governance_store_path=tmp_path / "governance.json",
        )
        client = TestClient(create_app(settings))
        steps: list[StepResult] = []
        system = _headers("SYSTEM_ADMIN", "sys-drill")
        ai = _headers("AI_ADMIN", "ai-drill")
        approver = _headers("AI_ADMIN", "ai-drill-approver")

        def record(name: str, response, *, expect: int = 200) -> dict:
            ok = response.status_code == expect
            detail = ""
            payload: dict = {}
            try:
                payload = response.json()
            except Exception:  # noqa: BLE001
                detail = response.text[:200]
            if not ok:
                detail = detail or str(payload.get("detail") or payload)[:240]
            steps.append(StepResult(name, ok, detail))
            return payload if ok else {}

        prompts = record("list prompts", client.get("/api/governance/prompts", headers=ai))
        prompt_id = ((prompts.get("items") or [{}])[0].get("prompt") or {}).get("prompt_id")
        flags = record("list flags", client.get("/api/governance/flags", headers=ai))
        record("list models", client.get("/api/governance/models", headers=ai))
        record("list retention", client.get("/api/governance/retention", headers=ai))
        record("list masking", client.get("/api/governance/masking", headers=ai))
        record("list roles", client.get("/api/governance/roles", headers=system))

        created_example = record(
            "create example",
            client.post(
                "/api/examples/manual",
                headers=system,
                json={
                    "text": "VPN 無法連線",
                    "expected_issue_type_id": "vpn.connection_failed",
                    "expected_route": "KNOWLEDGE",
                    "label": "POSITIVE",
                },
            ),
        )
        example = created_example.get("example") or {}
        verified = record(
            "verify example",
            client.post(
                f"/api/examples/{example.get('example_id')}/review",
                headers=system,
                json={"expected_etag": 1, "approve": True, "reason": "phase3 drill"},
            ),
        )
        taxonomy = record("taxonomy", client.get("/api/taxonomy", headers=ai))
        if prompt_id and verified.get("example"):
            candidate = record(
                "prompt candidate",
                client.post(
                    f"/api/governance/prompts/{prompt_id}/candidates",
                    headers={**ai, "Idempotency-Key": "phase3-drill-1"},
                    json={
                        "dataset_version": verified["example"]["dataset_version"],
                        "taxonomy_version": taxonomy.get("taxonomyVersion"),
                    },
                ),
            )
            version_id = (candidate.get("version") or {}).get("version_id")
            if version_id:
                record(
                    "prompt eval",
                    client.post(
                        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/eval",
                        headers=ai,
                    ),
                )
                record(
                    "prompt approve",
                    client.post(
                        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/approve",
                        headers=approver,
                        json={"reason": "phase3 drill approve"},
                    ),
                )
                record(
                    "prompt canary",
                    client.post(
                        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/canary",
                        headers=approver,
                        json={"percent": 5, "environment": "lab", "reason": "phase3 drill canary"},
                    ),
                )
                record(
                    "prompt canary evaluate continue",
                    client.post(
                        f"/api/governance/prompts/{prompt_id}/canary/evaluate",
                        headers=approver,
                        json={
                            "sample_size": 50,
                            "error_rate": 0.01,
                            "negative_feedback_rate": 0.01,
                            "handoff_rate": 0.01,
                            "safety_alerts": 0,
                        },
                    ),
                )
                record(
                    "prompt activate",
                    client.post(
                        f"/api/governance/prompts/{prompt_id}/versions/{version_id}/activate",
                        headers=approver,
                        json={"reason": "phase3 drill activate"},
                    ),
                )
                record(
                    "prompt rollback",
                    client.post(
                        f"/api/governance/prompts/{prompt_id}/rollback",
                        headers=approver,
                        json={"reason": "phase3 drill rollback"},
                    ),
                )

        flag_candidate = record(
            "flag candidate",
            client.post(
                "/api/governance/flags/candidates",
                headers=ai,
                json={
                    "flag_id": "feedback",
                    "value": "true",
                    "environment": "lab",
                    "reason": "phase3 drill flag",
                },
            ),
        )
        flag_version = (flag_candidate.get("version") or {}).get("version_id")
        if flag_version:
            record(
                "flag approve",
                client.post(
                    f"/api/governance/flags/feedback/versions/{flag_version}/approve",
                    headers=approver,
                    json={"reason": "phase3 drill flag approve"},
                ),
            )
            record(
                "flag activate",
                client.post(
                    f"/api/governance/flags/feedback/versions/{flag_version}/activate",
                    headers=approver,
                    json={"reason": "phase3 drill flag activate"},
                ),
            )

        retention = record(
            "retention candidate",
            client.post(
                "/api/governance/retention/candidates",
                headers=ai,
                json={
                    "policy_id": "operational-events",
                    "ttl_days": 180,
                    "migration_plan": "archive then delete for drill",
                    "reason": "phase3 drill retention",
                },
            ),
        )
        retention_id = (retention.get("policy") or {}).get("version_id")
        if retention_id:
            record(
                "retention approve",
                client.post(
                    f"/api/governance/retention/{retention_id}/approve",
                    headers=approver,
                    json={"reason": "phase3 drill retention approve"},
                ),
            )
            record(
                "retention activate",
                client.post(
                    f"/api/governance/retention/{retention_id}/activate",
                    headers=approver,
                    json={"reason": "phase3 drill retention activate"},
                ),
            )

        masking = record(
            "masking candidate",
            client.post(
                "/api/governance/masking/candidates",
                headers=ai,
                json={"policy_version": "mask-drill-v1", "reason": "phase3 drill masking"},
            ),
        )
        masking_id = (masking.get("policy") or {}).get("version_id")
        if masking_id:
            record(
                "masking approve",
                client.post(
                    f"/api/governance/masking/{masking_id}/approve",
                    headers=approver,
                    json={"reason": "phase3 drill masking approve"},
                ),
            )
            record(
                "masking activate",
                client.post(
                    f"/api/governance/masking/{masking_id}/activate",
                    headers=approver,
                    json={"reason": "phase3 drill masking activate"},
                ),
            )

        role_req = record(
            "role request",
            client.post(
                "/api/governance/roles/requests",
                headers=system,
                json={
                    "target_principal": "analyst.drill",
                    "target_role": "ANALYST",
                    "add_capabilities": ["ops.summary.read"],
                    "remove_capabilities": [],
                    "reason": "phase3 drill role",
                },
            ),
        )
        change_id = (role_req.get("change") or {}).get("change_id")
        if change_id:
            record(
                "role approve",
                client.post(
                    f"/api/governance/roles/{change_id}/approve",
                    headers=_headers("SYSTEM_ADMIN", "sys-drill-approver"),
                    json={"reason": "phase3 drill role approve"},
                ),
            )

        search = record(
            "governance search",
            client.get("/api/governance/search", params={"q": "issue"}, headers=ai),
        )
        if search.get("count", 0) < 1:
            steps.append(StepResult("governance search has hits", False, "count=0"))
        else:
            steps.append(StepResult("governance search has hits", True, f"count={search.get('count')}"))

        export = record(
            "audit export",
            client.get("/api/governance/audit/export", headers=system),
        )
        steps.append(
            StepResult(
                "audit export package",
                bool(export.get("format") == "json" and export.get("count", 0) >= 1),
                f"count={export.get('count')}",
            )
        )

        passed = all(step.passed for step in steps)
        payload = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "mode": "inprocess",
            "passed": passed,
            "stepCount": len(steps),
            "passedCount": sum(1 for step in steps if step.passed),
            "failedCount": sum(1 for step in steps if not step.passed),
            "promptId": prompt_id,
            "flagCount": len(flags.get("items") or []),
            "steps": [step.to_dict() for step in steps],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 3 governance LAB drill.")
    parser.add_argument(
        "--report",
        default="artifacts/ops_phase3_governance_drill.json",
        help="Output report path",
    )
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = (Path.cwd() / report_path).resolve()
    else:
        report_path = report_path.resolve()

    # Ensure agent_service src is importable when launched from repo root.
    agent_src = repo_root / "agent_service" / "src"
    if str(agent_src) not in sys.path:
        sys.path.insert(0, str(agent_src))

    payload = _run_inprocess(report_path)
    print(json.dumps({"passed": payload["passed"], "report": str(report_path)}, ensure_ascii=False))
    if not payload["passed"]:
        failed = [step for step in payload["steps"] if not step["passed"]]
        print(json.dumps(failed, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
