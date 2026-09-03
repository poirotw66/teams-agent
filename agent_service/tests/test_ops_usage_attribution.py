from __future__ import annotations

from agent_service.operations.usage_attribution import request_summary_payload
from agent_service.usage_events import RequestCostSummary, UsageEventCollector


def _summary(
    *,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: float | None,
    cost_complete: bool,
    event_count: int,
    llm_call_count: int,
) -> RequestCostSummary:
    return RequestCostSummary(
        request_id="req-1",
        correlation_id="corr-1",
        environment="test",
        tenant_id="tenant-1",
        team_id="team-1",
        outcome="knowledge_hit",
        knowledge_backend="HYBRID",
        elapsed_ms=125.0,
        llm_call_count=llm_call_count,
        event_count=event_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        embedding_tokens=0,
        estimated_cost_usd=estimated_cost_usd,
        cost_complete=cost_complete,
        usage_coverage=1.0 if event_count == 0 else 0.5,
        pricing_version="2026-01-01",
    )


def test_per_call_usage_keeps_models_separate_and_summary_is_not_top_level_metric() -> None:
    collector = UsageEventCollector(
        environment="test",
        request_id="req-1",
        correlation_id="corr-1",
        tenant_id="tenant-1",
        team_id="team-1",
        knowledge_backend="HYBRID",
        pricing_version="2026-01-01",
    )
    openai = collector.record(
        component="issue_extract",
        status="SUCCESS",
        latency_ms=12.0,
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=10,
        usage_source="PROVIDER",
    )
    google = collector.record(
        component="knowledge_generate",
        status="SUCCESS",
        latency_ms=23.0,
        model="gemini-2.5-flash",
        input_tokens=50,
        output_tokens=5,
        usage_source="PROVIDER",
    )
    total_cost = (openai.estimated_cost_usd or 0) + (google.estimated_cost_usd or 0)
    summary = _summary(
        input_tokens=150,
        output_tokens=15,
        estimated_cost_usd=total_cost,
        cost_complete=True,
        event_count=2,
        llm_call_count=2,
    )

    from agent_service.operations.usage_attribution import call_usage_payload

    calls = [call_usage_payload(event, call_ordinal=index) for index, event in enumerate(collector.events(), 1)]
    request_payload = request_summary_payload(summary, collector.events())

    assert [(call["model"], call["provider"], call["component"]) for call in calls] == [
        ("gpt-4o-mini", "openai", "issue_extract"),
        ("gemini-2.5-flash", "google", "knowledge_generate"),
    ]
    assert sum(call["estimatedCostUsd"] for call in calls) == total_cost
    assert "estimatedCostUsd" not in request_payload
    assert request_payload["summary"]["estimatedCostUsd"] == total_cost
    assert request_payload["perCallReconciliation"] == {
        "collectorEventCount": 2,
        "inputTokensMatch": True,
        "outputTokensMatch": True,
        "estimatedCostUsdMatch": True,
        "unknownCallCostPresent": False,
    }


def test_unknown_price_remains_unknown_and_zero_call_summary_is_not_marked_incomplete() -> None:
    collector = UsageEventCollector(
        environment="test",
        request_id="req-1",
        correlation_id="corr-1",
        tenant_id="tenant-1",
        team_id="team-1",
        knowledge_backend="HYBRID",
    )
    unknown = collector.record(
        component="fallback_model",
        status="SUCCESS",
        latency_ms=3.0,
        model="unknown-provider-model",
        input_tokens=4,
        output_tokens=2,
        usage_source="PROVIDER",
    )
    unknown_summary = _summary(
        input_tokens=4,
        output_tokens=2,
        estimated_cost_usd=None,
        cost_complete=False,
        event_count=1,
        llm_call_count=1,
    )
    unknown_payload = request_summary_payload(unknown_summary, collector.events())
    assert unknown.estimated_cost_usd is None
    assert unknown_payload["summary"]["estimatedCostUsd"] is None
    assert unknown_payload["summary"]["costComplete"] is False
    assert unknown_payload["perCallReconciliation"]["estimatedCostUsdMatch"] is None

    zero_summary = _summary(
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=None,
        cost_complete=True,
        event_count=0,
        llm_call_count=0,
    )
    zero_payload = request_summary_payload(zero_summary, ())
    assert zero_payload["summary"]["costComplete"] is True
    assert zero_payload["perCallReconciliation"]["unknownCallCostPresent"] is False
