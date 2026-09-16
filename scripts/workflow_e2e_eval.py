"""Run the workflow routing evaluation set against an Agent HTTP endpoint."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class CaseResult(TypedDict):
    caseId: str
    passed: bool
    expectedRoute: str
    observedRoute: str
    expectedIssueCount: int
    observedIssueCount: int
    ticketCreated: bool
    latencyMs: float
    error: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=Path("data/eval/workflow_routing_eval_set.json"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tenant-id", default="workflow-eval")
    parser.add_argument("--token-env", default="AGENT_SERVICE_TOKEN")
    parser.add_argument("--timeout-seconds", type=float, default=90)
    return parser.parse_args()


def validate_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url must be an absolute HTTP(S) URL.")
    return base_url.rstrip("/")


def request_payload(
    *,
    text: str,
    tenant_id: str,
    conversation_id: str,
) -> dict:
    request_id = f"eval-{uuid.uuid4().hex}"
    return {
        "requestId": request_id,
        "channel": "playground",
        "conversation": {
            "tenantId": tenant_id,
            "conversationId": conversation_id,
        },
        "user": {
            "teamsUserId": "workflow-eval-user",
            "displayName": "Workflow Evaluation",
        },
        "message": {"text": text, "locale": "zh-TW"},
    }


def post_turn(
    url: str,
    payload: dict,
    *,
    token: str | None,
    timeout_seconds: float,
) -> tuple[dict, float]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started_at = time.perf_counter()
    with urlopen(request, timeout=timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body, (time.perf_counter() - started_at) * 1000


def observed_route(response: dict) -> str:
    result_types = {
        str(item.get("resultType", ""))
        for item in response.get("issueResults", [])
        if isinstance(item, dict)
    }
    if "TICKET_CREATED" in result_types:
        return "TICKET"
    if result_types & {"KNOWLEDGE_ANSWERED", "FAQ_ANSWERED"}:
        return "KNOWLEDGE"
    if "NEED_MORE_INFO" in result_types:
        return "CLARIFICATION"
    if result_types & {"NO_KNOWLEDGE", "FAILED"}:
        return "NO_KNOWLEDGE"
    return "UNKNOWN"


def route_matches(expected: str, observed: str) -> bool:
    if expected == "KNOWLEDGE_OR_NO_KNOWLEDGE":
        return observed in {"KNOWLEDGE", "NO_KNOWLEDGE"}
    return expected == observed


def execute_case(
    base_url: str,
    case: dict,
    *,
    tenant_id: str,
    token: str | None,
    timeout_seconds: float,
) -> CaseResult:
    expected = case["expected"]
    conversation_id = f"workflow-eval-{case['id']}-{uuid.uuid4().hex}"
    response: dict = {}
    total_latency_ms = 0.0
    try:
        for text in case["turns"]:
            response, latency_ms = post_turn(
                f"{base_url}/agent/chat",
                request_payload(
                    text=text,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                ),
                token=token,
                timeout_seconds=timeout_seconds,
            )
            total_latency_ms += latency_ms
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        return {
            "caseId": case["id"],
            "passed": False,
            "expectedRoute": expected["route"],
            "observedRoute": "ERROR",
            "expectedIssueCount": expected["issueCount"],
            "observedIssueCount": 0,
            "ticketCreated": False,
            "latencyMs": round(total_latency_ms, 1),
            "error": f"{type(error).__name__}: {error}",
        }

    route = observed_route(response)
    issue_results = response.get("issueResults", [])
    ticket_created = any(
        item.get("resultType") == "TICKET_CREATED"
        for item in issue_results
        if isinstance(item, dict)
    )
    passed = all(
        (
            route_matches(expected["route"], route),
            len(issue_results) == expected["issueCount"],
            ticket_created is expected["ticketCreated"],
        )
    )
    return {
        "caseId": case["id"],
        "passed": passed,
        "expectedRoute": expected["route"],
        "observedRoute": route,
        "expectedIssueCount": expected["issueCount"],
        "observedIssueCount": len(issue_results),
        "ticketCreated": ticket_created,
        "latencyMs": round(total_latency_ms, 1),
        "error": None,
    }


def summarize(results: list[CaseResult]) -> dict:
    latencies = sorted(result["latencyMs"] for result in results)
    p95_index = max(0, int(len(latencies) * 0.95 + 0.999999) - 1)
    passed = sum(result["passed"] for result in results)
    return {
        "caseCount": len(results),
        "passedCount": passed,
        "conformanceRate": passed / len(results),
        "meanLatencyMs": round(statistics.fmean(latencies), 1),
        "p95LatencyMs": latencies[p95_index],
        "retrievalQueryAccuracy": None,
        "llmCallCount": None,
        "limitations": [
            "HTTP responses do not expose normalized retrieval queries.",
            "HTTP responses do not expose per-request LLM call counts.",
        ],
    }


def main() -> int:
    args = parse_args()
    base_url = validate_base_url(args.base_url)
    evaluation_set = json.loads(args.eval_set.read_text(encoding="utf-8"))
    token = os.environ.get(args.token_env)
    results = [
        execute_case(
            base_url,
            case,
            tenant_id=args.tenant_id,
            token=token,
            timeout_seconds=args.timeout_seconds,
        )
        for case in evaluation_set["cases"]
    ]
    report = {"summary": summarize(results), "cases": results}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if report["summary"]["passedCount"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
