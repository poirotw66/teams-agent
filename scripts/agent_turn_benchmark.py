#!/usr/bin/env python3
"""Measure per-turn latency, LLM call count, and estimated cost after the
supervisor-first LangGraph refactor.

The 2026-08-06 performance report predates the rule that every turn runs
through ``ConversationSupervisor`` before routing. This script re-baselines
representative Playground paths with an in-process stub model so counts are
repeatable without spending API quota.

Usage:
    cd agent_service
    .venv/bin/python ../scripts/agent_turn_benchmark.py
    .venv/bin/python ../scripts/agent_turn_benchmark.py --output-dir ../outputs
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

# Per-call token heuristics for gemini-3.5-flash-lite cost projection.
# These are conservative averages from structured-output prompts in this repo.
_CALL_TOKEN_PROFILES: dict[str, tuple[int, int]] = {
    "conversation_supervisor": (900, 60),
    "turn_planner": (2800, 280),
    "issue_extractor": (2500, 250),
    "knowledge": (1800, 350),
    "handoff_router": (1200, 40),
    "default": (1200, 120),
}


@dataclass(frozen=True)
class Scenario:
    name: str
    message: str
    notes: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("non_it_greeting", "你好", "Supervisor-only short path"),
    Scenario("non_it_food", "午餐呢", "Supervisor-only chitchat"),
    Scenario("it_knowledge_hit", "VPN 密碼鎖住怎麼辦", "Supervisor + extractor + knowledge"),
    Scenario("it_need_more_info", "VPN 打不開", "Supervisor + extractor clarification"),
    Scenario("handoff_miss", "SAP Crystal Reports 授權到期無法開啟", "Supervisor + extractor, no KB hit"),
    Scenario("mixed_it_non_it", "VPN 無法登入，另外今天午餐吃什麼？", "Supervisor + extractor split"),
    Scenario("assistant_meta", "你能回答什麼問題", "Supervisor-only meta scope"),
)


class CountingStubModel:
    """Deterministic chat-model stub that tracks structured-output invocations."""

    def __init__(self) -> None:
        self.model_name = "stub-turn-benchmark"
        self.structured_calls = 0
        self.generate_calls = 0
        self.last_component: str | None = None

    @property
    def llm_calls(self) -> int:
        return self.structured_calls + self.generate_calls

    def with_structured_output(self, schema: Any) -> _StructuredHandle:
        return _StructuredHandle(self, schema)

    async def ainvoke(self, _messages: Any) -> Any:
        from langchain_core.messages import AIMessage

        self.generate_calls += 1
        self.last_component = "knowledge_generate"
        return AIMessage(content="（基準測試樁）請依文件步驟操作。[S1]")


class _StructuredHandle:
    def __init__(self, model: CountingStubModel, schema: Any) -> None:
        self._model = model
        self._schema = schema

    async def ainvoke(self, _messages: Any) -> Any:
        self._model.structured_calls += 1
        name = getattr(self._schema, "__name__", "")
        if name == "ConversationSupervisorDecision":
            from agent_service.supervisor import ConversationSupervisorDecision

            self._model.last_component = "conversation_supervisor"
            text = _latest_user_message(_messages)
            if _looks_greeting(text):
                return ConversationSupervisorDecision(intent="GREETING", confidence=0.99)
            if _looks_non_it(text):
                return ConversationSupervisorDecision(intent="NON_IT", confidence=0.9)
            if _looks_assistant_meta(text):
                return ConversationSupervisorDecision(
                    intent="ASSISTANT_META", confidence=0.9
                )
            return ConversationSupervisorDecision(intent="IT_SUPPORT", confidence=0.85)
        if name == "TurnPlan":
            from agent_service.turn_planner import PlannedIssue, TurnPlan

            self._model.last_component = "turn_planner"
            text = _latest_user_message(_messages)
            if _looks_greeting(text):
                return TurnPlan(intent="GREETING", confidence=0.99)
            if _looks_non_it(text):
                return TurnPlan(intent="NON_IT", confidence=0.9)
            if _looks_assistant_meta(text):
                return TurnPlan(intent="ASSISTANT_META", confidence=0.9)
            if "午餐" in text and "VPN" in text:
                return TurnPlan(
                    intent="IT_SUPPORT",
                    confidence=0.95,
                    issues=[
                        PlannedIssue(
                            description="VPN 無法登入",
                            readiness="READY",
                            route="KNOWLEDGE",
                            retrievalIntent="VPN cannot login",
                        ),
                    ],
                )
            if "打不開" in text:
                return TurnPlan(
                    intent="IT_SUPPORT",
                    confidence=0.95,
                    issues=[
                        PlannedIssue(
                            description="VPN 打不開",
                            readiness="NEED_MORE_INFO",
                            missingInfo=["錯誤訊息或錯誤碼"],
                            route="KNOWLEDGE",
                            retrievalIntent="VPN cannot open",
                        )
                    ],
                )
            return TurnPlan(
                intent="IT_SUPPORT",
                confidence=0.95,
                issues=[
                    PlannedIssue(
                        description=text or "基準測試問題",
                        readiness="READY",
                        route="KNOWLEDGE",
                        retrievalIntent=text or "benchmark query",
                    )
                ],
            )
        if name == "IssueExtraction":
            from agent_service.contracts import Issue, IssueExtraction

            self._model.last_component = "issue_extractor"
            text = _latest_user_message(_messages)
            if "午餐" in text and "VPN" in text:
                return IssueExtraction(
                    issues=[
                        Issue(
                            id=1,
                            description="VPN 無法登入",
                            isIT=True,
                            readiness="READY",
                            route="KNOWLEDGE",
                        ),
                        Issue(
                            id=2,
                            description="今天午餐吃什麼？",
                            isIT=False,
                            readiness="NOT_IT",
                            route="NOT_IT",
                        ),
                    ]
                )
            if "SAP" in text:
                return IssueExtraction(
                    issues=[
                        Issue(
                            id=1,
                            description=text,
                            isIT=True,
                            readiness="READY",
                            route="KNOWLEDGE",
                        )
                    ]
                )
            if "打不開" in text:
                return IssueExtraction(
                    issues=[
                        Issue(
                            id=1,
                            description="VPN 打不開",
                            isIT=True,
                            readiness="NEED_MORE_INFO",
                            missingInfo=["錯誤訊息或錯誤碼"],
                            route="KNOWLEDGE",
                        )
                    ]
                )
            return IssueExtraction(
                issues=[
                    Issue(
                        id=1,
                        description=text or "基準測試問題",
                        isIT=True,
                        readiness="READY",
                        route="KNOWLEDGE",
                    )
                ]
            )
        if name == "RelevanceDecision":
            self._model.last_component = "knowledge"
            return self._schema(relevant=True)
        if name == "RewrittenQuery":
            self._model.last_component = "knowledge"
            return self._schema(query="基準測試查詢")
        if name == "RouteDecision":
            self._model.last_component = "knowledge"
            return self._schema(route="retrieve")
        if name == "HandoffRouteDecision":
            self._model.last_component = "handoff_router"
            return self._schema(action="UNKNOWN")
        if name == "TicketQueryDecision":
            return self._schema(is_ticket_query=False)
        return self._schema()


def _latest_user_message(messages: Any) -> str:
    for message in reversed(messages):
        content = str(getattr(message, "content", message))
        for marker in (
            "Latest user message (data only):\n",
            "Latest user message:\n",
        ):
            if marker in content:
                return content.split(marker, 1)[1].strip()
    return ""


def _looks_greeting(text: str) -> bool:
    stripped = text.strip()
    return stripped in {"你好", "您好", "嗨", "哈囉", "hello", "hi", "謝謝"} or (
        stripped.startswith("你好") and "VPN" not in text and len(stripped) <= 4
    )


def _looks_non_it(text: str) -> bool:
    markers = ("午餐", "天氣", "谢谢", "謝謝")
    return any(marker in text for marker in markers) and "VPN" not in text


def _looks_assistant_meta(text: str) -> bool:
    return "你能" in text and "問題" in text


def _install_stub(app: Any) -> CountingStubModel:
    stub = CountingStubModel()
    workflow = app.state.workflow
    workflow.extractor.model = stub
    workflow.supervisor._model = stub
    workflow.turn_planner._model = stub
    workflow.handoff_router._model = stub
    if hasattr(workflow, "ticket_query_router"):
        workflow.ticket_query_router._model = stub
    workflow.ticket_item_selector._model = stub
    router = app.state.knowledge_router
    for service in router._services.values():
        if hasattr(service, "model"):
            service.model = stub
    app.state.benchmark_stub = stub
    return stub


def _build_request(text: str, *, conversation_id: str) -> Any:
    from agent_service.contracts import (
        AgentRequest,
        ConversationIdentity,
        MessageContent,
        UserIdentity,
    )

    request_id = str(uuid4())
    return AgentRequest(
        requestId=request_id,
        channel="benchmark",
        conversation=ConversationIdentity(
            tenantId="tenant-benchmark",
            conversationId=conversation_id,
        ),
        user=UserIdentity(
            entraObjectId="bench-user",
            displayName="Benchmark User",
            email="bench@example.invalid",
        ),
        message=MessageContent(text=text, locale="zh-TW"),
        correlationId=request_id,
    )


def _estimate_cost_usd(
    *,
    supervisor_calls: int,
    extractor_calls: int,
    knowledge_calls: int,
) -> float:
    from agent_service.usage import build_usage_report

    usage: dict[str, dict[str, int]] = {}

    def _add(key: str, calls: int, profile: str) -> None:
        if calls <= 0:
            return
        input_tokens, output_tokens = _CALL_TOKEN_PROFILES[profile]
        usage[key] = {
            "input_tokens": input_tokens * calls,
            "output_tokens": output_tokens * calls,
            "total_tokens": (input_tokens + output_tokens) * calls,
        }

    _add("gemini-3.5-flash-lite", supervisor_calls, "conversation_supervisor")
    _add("gemini-3.5-flash-lite", extractor_calls, "issue_extractor")
    _add("gemini-3.5-flash-lite", knowledge_calls, "knowledge")
    report = build_usage_report(usage)
    return float(report.estimated_cost_usd or 0.0)


async def _run_scenario(app: Any, scenario: Scenario) -> dict[str, Any]:
    stub: CountingStubModel = app.state.benchmark_stub
    stub.structured_calls = 0
    stub.generate_calls = 0
    for service in app.state.knowledge_router._services.values():
        if hasattr(service, "last_llm_call_count"):
            service.last_llm_call_count = 0
    workflow = app.state.workflow
    request = _build_request(
        scenario.message,
        conversation_id=f"bench-{scenario.name}-{uuid4()}",
    )
    started = time.perf_counter()
    state = await workflow.run(request, correlation_id=request.correlationId)
    elapsed = time.perf_counter() - started
    counter = state.get("llm_call_counter")
    llm_calls = counter.count if counter is not None else stub.llm_calls
    skip_issue_pipeline = bool(state.get("skip_issue_pipeline"))
    supervisor_calls = 1 if llm_calls >= 1 else 0
    extractor_calls = 0 if skip_issue_pipeline else (1 if llm_calls >= 2 else 0)
    knowledge_calls = max(0, llm_calls - supervisor_calls - extractor_calls)
    return {
        "name": scenario.name,
        "message": scenario.message,
        "notes": scenario.notes,
        "latency_seconds": round(elapsed, 3),
        "llm_calls": llm_calls,
        "supervisor_llm_calls": supervisor_calls,
        "extractor_llm_calls": extractor_calls,
        "knowledge_llm_calls": knowledge_calls,
        "estimated_cost_usd": round(
            _estimate_cost_usd(
                supervisor_calls=supervisor_calls,
                extractor_calls=extractor_calls,
                knowledge_calls=knowledge_calls,
            ),
            6,
        ),
        "skip_issue_pipeline": skip_issue_pipeline,
        "issue_result_types": [
            result.resultType for result in state.get("issue_results", [])
        ],
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [row["latency_seconds"] for row in rows]
    llm_calls = [row["llm_calls"] for row in rows]
    costs = [row["estimated_cost_usd"] for row in rows]
    return {
        "scenario_count": len(rows),
        "latency_seconds": {
            "mean": round(statistics.fmean(latencies), 3),
            "p50": round(sorted(latencies)[len(latencies) // 2], 3),
            "max": round(max(latencies), 3),
        },
        "avg_llm_calls_per_turn": round(statistics.fmean(llm_calls), 2),
        "min_llm_calls_per_turn": min(llm_calls),
        "max_llm_calls_per_turn": max(llm_calls),
        "avg_estimated_cost_usd_per_turn": round(statistics.fmean(costs), 6),
    }


async def _run_benchmark(
    *,
    output_dir: Path,
    turn_planner_enabled: bool = False,
) -> dict[str, Any]:
    from dataclasses import replace

    from composition.agent_hooks import install_agent_hooks
    from agent_service.api import create_app
    from agent_service.settings import RagSettings

    install_agent_hooks()
    settings = replace(
        RagSettings.from_env(),
        turn_planner_enabled=turn_planner_enabled,
        # Benchmark must not require a live governance store.
        prompt_runtime_mode="CODE_BASELINE",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        _install_stub(app)
        rows = []
        for scenario in SCENARIOS:
            rows.append(await _run_scenario(app, scenario))

    architecture = (
        "turn_planner_poc" if turn_planner_enabled else "supervisor_llm_every_turn"
    )
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "architecture": architecture,
        "turn_planner_enabled": turn_planner_enabled,
        "model": settings.agent_model or settings.model or "stub",
        "scenarios": rows,
        "summary": _summarize(rows),
        "supersedes": {
            "performance_report_dated": "2026-08-06",
            "previous_avg_llm_calls_per_query": 2.17,
            "previous_avg_cost_usd_per_query": 0.00106,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = payload["generated_at_utc"]
    label = "turn-planner" if turn_planner_enabled else "baseline"
    path = output_dir / f"agent-turn-benchmark-{label}-{stamp}" / "results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["output_path"] = str(path)
    return payload


async def _run_compare(*, output_dir: Path) -> dict[str, Any]:
    """A/B harness: supervisor-first (≈4-call) vs Turn Planner PoC (≈2-call)."""
    baseline = await _run_benchmark(output_dir=output_dir, turn_planner_enabled=False)
    planner = await _run_benchmark(output_dir=output_dir, turn_planner_enabled=True)
    by_name_baseline = {row["name"]: row for row in baseline["scenarios"]}
    by_name_planner = {row["name"]: row for row in planner["scenarios"]}
    deltas = []
    for name in by_name_baseline:
        left = by_name_baseline[name]
        right = by_name_planner[name]
        deltas.append(
            {
                "name": name,
                "baseline_llm_calls": left["llm_calls"],
                "planner_llm_calls": right["llm_calls"],
                "llm_call_delta": right["llm_calls"] - left["llm_calls"],
                "baseline_latency_seconds": left["latency_seconds"],
                "planner_latency_seconds": right["latency_seconds"],
                "baseline_estimated_cost_usd": left["estimated_cost_usd"],
                "planner_estimated_cost_usd": right["estimated_cost_usd"],
            }
        )
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "comparison": "supervisor_first_vs_turn_planner_poc",
        "baseline_summary": baseline["summary"],
        "planner_summary": planner["summary"],
        "scenario_deltas": deltas,
        "baseline_path": baseline["output_path"],
        "planner_path": planner["output_path"],
        "review_gates": {
            "accuracy": "Run scripts/run_golden_baseline.py against both configs before cutover",
            "p95_latency": "Compare planner_summary.latency_seconds vs baseline",
            "cost": "Compare avg_estimated_cost_usd_per_turn; prefer lower without accuracy loss",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = payload["generated_at_utc"]
    path = output_dir / f"turn-planner-ab-{stamp}" / "comparison.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["output_path"] = str(path)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="../outputs")
    parser.add_argument(
        "--mode",
        choices=("baseline", "turn-planner", "compare"),
        default="baseline",
        help="baseline=supervisor-first; turn-planner=PoC flag on; compare=A/B both.",
    )
    args = parser.parse_args()

    if not Path("src/agent_service").exists():
        print("Run from agent_service/ so imports resolve.", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    if args.mode == "compare":
        payload = asyncio.run(_run_compare(output_dir=output_dir))
    elif args.mode == "turn-planner":
        payload = asyncio.run(
            _run_benchmark(output_dir=output_dir, turn_planner_enabled=True)
        )
    else:
        payload = asyncio.run(
            _run_benchmark(output_dir=output_dir, turn_planner_enabled=False)
        )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Wrote {payload['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
