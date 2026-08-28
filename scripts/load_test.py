#!/usr/bin/env python3
"""Concurrent load driver for the Agent Service (spec §16, §19 item 22).

Spec §2.1 forbids rewriting the runtime language on the basis of an untested
performance assumption; §16 fixes the optimisation order and puts "adjust the
runtime" dead last, *after* load-test data exists. This script exists to
produce that data.

Two modes:

``--dry-run``
    Drives the FastAPI app in-process through ``httpx.ASGITransport`` with a
    stubbed chat model, so latency of the *framework and workflow* can be
    measured without spending API quota. Retrieval still runs for real
    against the built index.

``--target URL --i-know-this-hits-a-real-service``
    Drives a running Agent Service over HTTP. The second flag is mandatory:
    without it the script refuses to send load anywhere, so nobody
    accidentally load-tests production.

Reports throughput, P50/P95/P99 latency, error rate, and LLM calls per
request. Never imported by pytest.

Usage:
    cd agent_service
    .venv/bin/python ../scripts/load_test.py --dry-run --concurrency 8 --requests 40
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

# Default question mix. Kept small and representative rather than exhaustive:
# an FAQ hit (no LLM retrieval), a knowledge lookup, a multi-issue message,
# and a deliberate no-answer, so the mix exercises the cheap and expensive
# paths in roughly the proportion a real IT channel would.
DEFAULT_QUERIES = [
    "金控入口網的密碼要怎麼變更？",
    "VPN連線出現 Permission denied (-455) 這個錯誤要怎麼處理？",
    "VPN無法登入，另外Outlook一直要求重新登入",
    "公司員工的育嬰假天數上限是多少？",
]


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile. Matches scripts/retrieval_ab_test.py."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]


@dataclass
class RequestOutcome:
    latency_seconds: float
    status_code: int
    ok: bool
    llm_calls: int | None = None
    error: str | None = None


@dataclass
class LoadReport:
    concurrency: int
    total_requests: int
    wall_seconds: float
    outcomes: list[RequestOutcome] = field(default_factory=list)

    @property
    def successes(self) -> list[RequestOutcome]:
        return [outcome for outcome in self.outcomes if outcome.ok]

    def to_dict(self) -> dict[str, Any]:
        latencies = [outcome.latency_seconds for outcome in self.successes]
        failures = len(self.outcomes) - len(self.successes)
        llm_calls = [
            outcome.llm_calls for outcome in self.successes if outcome.llm_calls is not None
        ]
        return {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "concurrency": self.concurrency,
            "total_requests": self.total_requests,
            "wall_seconds": round(self.wall_seconds, 3),
            "throughput_rps": (
                round(len(self.successes) / self.wall_seconds, 3) if self.wall_seconds else 0.0
            ),
            "error_rate": (
                round(failures / len(self.outcomes), 4) if self.outcomes else 0.0
            ),
            "failures": failures,
            "latency_seconds": {
                "p50": round(percentile(latencies, 0.50), 3),
                "p95": round(percentile(latencies, 0.95), 3),
                "p99": round(percentile(latencies, 0.99), 3),
                "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
                "max": round(max(latencies), 3) if latencies else 0.0,
            },
            "avg_llm_calls_per_request": (
                round(statistics.fmean(llm_calls), 3) if llm_calls else None
            ),
            "status_codes": _count_status_codes(self.outcomes),
        }


def _count_status_codes(outcomes: list[RequestOutcome]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for outcome in outcomes:
        key = str(outcome.status_code)
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_payload(text: str) -> dict[str, Any]:
    correlation_id = str(uuid4())
    return {
        "requestId": correlation_id,
        "channel": "msteams",
        "conversation": {
            "tenantId": None,
            # Each virtual user gets its own conversation so the run does not
            # serialise on a single conversation's history.
            "conversationId": f"load-{uuid4()}",
        },
        "user": {
            "teamsUserId": f"load-user-{uuid4()}",
            "entraObjectId": str(uuid4()),
            "displayName": "Load Test User",
            "email": "load-test@example.invalid",
            "groups": [],
        },
        "message": {"text": text},
        "correlationId": correlation_id,
    }


async def _issue(client: Any, url: str, text: str, headers: dict[str, str]) -> RequestOutcome:
    started = time.perf_counter()
    try:
        response = await client.post(url, json=build_payload(text), headers=headers)
    except Exception as error:  # noqa: BLE001 - any transport failure counts as an error
        return RequestOutcome(
            latency_seconds=time.perf_counter() - started,
            status_code=0,
            ok=False,
            error=type(error).__name__,
        )
    latency = time.perf_counter() - started
    ok = response.status_code == 200
    llm_calls: int | None = None
    if ok:
        try:
            body = response.json()
            # issueResults is the closest per-request signal the response
            # exposes; the authoritative LLM call count is in the service log
            # line (§15.2 llm_call_count).
            llm_calls = len(body.get("issueResults") or []) or None
        except Exception:  # noqa: BLE001 - a malformed body is still a success/failure signal
            llm_calls = None
    return RequestOutcome(
        latency_seconds=latency,
        status_code=response.status_code,
        ok=ok,
        llm_calls=llm_calls,
    )


async def run_load(
    client: Any,
    url: str,
    *,
    concurrency: int,
    total_requests: int,
    queries: list[str],
    headers: dict[str, str],
) -> LoadReport:
    semaphore = asyncio.Semaphore(concurrency)

    async def worker(index: int) -> RequestOutcome:
        async with semaphore:
            return await _issue(client, url, queries[index % len(queries)], headers)

    started = time.perf_counter()
    outcomes = await asyncio.gather(*(worker(index) for index in range(total_requests)))
    wall = time.perf_counter() - started
    return LoadReport(
        concurrency=concurrency,
        total_requests=total_requests,
        wall_seconds=wall,
        outcomes=list(outcomes),
    )


class _StubModel:
    """Deterministic stand-in for the chat model in --dry-run mode.

    Returns a fixed grounded-looking answer so no API quota is spent. This
    measures framework/workflow/retrieval latency, NOT model latency — the
    report must say so.
    """

    def __init__(self) -> None:
        self.model_name = "stub-dry-run"

    def with_structured_output(self, schema: Any) -> _StubStructured:
        return _StubStructured(schema)

    async def ainvoke(self, _messages: Any) -> Any:
        from langchain_core.messages import AIMessage

        return AIMessage(content="（壓測樁）根據內部知識庫，請依文件步驟操作。[S1]")


class _StubStructured:
    def __init__(self, schema: Any) -> None:
        self.schema = schema

    async def ainvoke(self, _messages: Any) -> Any:
        name = getattr(self.schema, "__name__", "")
        if name == "IssueExtraction":
            from agent_service.contracts import Issue, IssueExtraction

            return IssueExtraction(
                issues=[
                    Issue(
                        id=1,
                        description="壓測問題",
                        isIT=True,
                        readiness="READY",
                        missingInfo=[],
                        route="KNOWLEDGE",
                    )
                ]
            )
        if name == "RelevanceDecision":
            return self.schema(relevant=True)
        if name == "RewrittenQuery":
            return self.schema(query="壓測查詢")
        if name == "RouteDecision":
            return self.schema(route="retrieve")
        return self.schema()


async def _dry_run(args: argparse.Namespace) -> LoadReport:
    import httpx
    from agent_service.api import create_app
    from agent_service.settings import RagSettings

    settings = RagSettings.from_env()
    app = create_app(settings)

    transport = httpx.ASGITransport(app=app)
    # Trigger lifespan so the index/services are built, then swap in the stub
    # model so no real LLM call is made.
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://load.test") as client,
        app.router.lifespan_context(app),
    ):
        _install_stub_model(app)
        return await run_load(
            client,
            "/agent/chat",
            concurrency=args.concurrency,
            total_requests=args.requests,
            queries=DEFAULT_QUERIES,
            headers={},
        )


def _install_stub_model(app: Any) -> None:
    """Replace every real model reference reachable from app.state."""
    stub = _StubModel()
    workflow = getattr(app.state, "workflow", None)
    if workflow is not None:
        for attr in ("extractor", "knowledge_service", "knowledge"):
            target = getattr(workflow, attr, None)
            if target is not None and hasattr(target, "model"):
                target.model = stub
    agent = getattr(app.state, "agent", None)
    if agent is not None and hasattr(agent, "model"):
        agent.model = stub


def _remote_auth_header(args: argparse.Namespace) -> dict[str, str]:
    """Build the Authorization header for a remote target.

    Two auth modes are supported, matching how the Teams Adapter reaches the
    Agent Service (see AGENT_API_AUTH_MODE in the adapter settings):

    - ``service-token``: a shared bearer token in ``AGENT_SERVICE_TOKEN``.
    - ``google-id-token``: a Cloud Run IAM identity token. A private Cloud
      Run service (``--no-allow-unauthenticated``) rejects a service token
      with 403 — it wants an identity token whose audience is the service
      URL, so this is the mode that actually works against a deployed
      Agent Service.

    ``auto`` (the default) prefers AGENT_SERVICE_TOKEN when it is set and
    otherwise mints an identity token via gcloud.
    """
    mode = args.auth
    token = os.environ.get("AGENT_SERVICE_TOKEN", "").strip()

    if mode == "service-token" or (mode == "auto" and token):
        if not token:
            raise SystemExit("--auth service-token requires AGENT_SERVICE_TOKEN to be set.")
        return {"Authorization": f"Bearer {token}"}

    if mode == "none":
        return {}

    identity_token = subprocess.run(
        ["gcloud", "auth", "print-identity-token"],
        capture_output=True,
        text=True,
        check=False,
    )
    if identity_token.returncode != 0 or not identity_token.stdout.strip():
        raise SystemExit(
            "could not obtain a Google identity token via "
            "`gcloud auth print-identity-token`. Authenticate with gcloud, or "
            "pass --auth service-token with AGENT_SERVICE_TOKEN set, or "
            "--auth none for an unauthenticated target."
        )
    return {"Authorization": f"Bearer {identity_token.stdout.strip()}"}


async def _remote_run(args: argparse.Namespace) -> LoadReport:
    import httpx

    headers = _remote_auth_header(args)

    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await run_load(
            client,
            args.target.rstrip("/") + "/agent/chat",
            concurrency=args.concurrency,
            total_requests=args.requests,
            queries=DEFAULT_QUERIES,
            headers=headers,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Run in-process with a stub model.")
    parser.add_argument("--target", help="Base URL of a running Agent Service.")
    parser.add_argument(
        "--i-know-this-hits-a-real-service",
        action="store_true",
        help="Required with --target. Guards against accidentally load-testing production.",
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--auth",
        choices=["auto", "google-id-token", "service-token", "none"],
        default="auto",
        help="How to authenticate to --target. A private Cloud Run service needs "
        "google-id-token; auto uses AGENT_SERVICE_TOKEN when set, else gcloud.",
    )
    parser.add_argument("--output-dir", default="../outputs")
    args = parser.parse_args()

    if not args.dry_run and not args.target:
        parser.error("Pass either --dry-run or --target URL.")
    if args.target and not args.i_know_this_hits_a_real_service:
        parser.error(
            "--target sends real load. Re-run with --i-know-this-hits-a-real-service "
            "to confirm you are not pointing at production."
        )

    report = asyncio.run(_dry_run(args) if args.dry_run else _remote_run(args))
    payload = report.to_dict()
    payload["mode"] = "dry-run (stub model)" if args.dry_run else f"remote {args.target}"

    print(json.dumps(payload, indent=2, ensure_ascii=False))

    output_dir = Path(args.output_dir) / (
        f"load-test-{payload['generated_at_utc']}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {output_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
