"""Projection of request-scoped usage collector records into ops payloads.

The collector is the source for per-call facts.  ``RequestCostSummary`` is a
separate request-level fact for reconciliation and must never be summed with
the call records.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from math import isclose
from typing import Any

from ..usage_events import RequestCostSummary, UsageEvent
from .event_identity import required_utc


def _total_tokens(event: UsageEvent) -> int:
    return (
        event.input_tokens
        + event.tool_context_tokens
        + event.output_tokens
        + event.embedding_tokens
    )


def call_usage_payload(event: UsageEvent, *, call_ordinal: int) -> dict[str, Any]:
    """Preserve observed facts and derive conservative coverage flags."""
    if call_ordinal < 1:
        raise ValueError("call_ordinal must be positive")
    return {
        "attributionScope": "CALL",
        "callOrdinal": call_ordinal,
        "collectorEventId": event.event_id,
        "collectorTimestamp": event.timestamp,
        "component": event.component,
        "provider": event.provider,
        "model": event.model,
        "knowledgeBackend": event.knowledge_backend,
        "inputTokens": event.input_tokens,
        "toolContextTokens": event.tool_context_tokens,
        "outputTokens": event.output_tokens,
        "embeddingTokens": event.embedding_tokens,
        "totalTokens": _total_tokens(event),
        "llmCallCount": event.llm_call_count,
        "estimatedCostUsd": event.estimated_cost_usd,
        "usageComplete": event.usage_source != "MISSING",
        "costComplete": event.usage_source != "MISSING" and event.estimated_cost_usd is not None,
        "pricingVersion": event.pricing_version,
        "usageSource": event.usage_source,
        "status": event.status,
        "elapsedMs": round(event.latency_ms, 1),
    }


def call_occurred_at(event: UsageEvent) -> datetime:
    """Use the collector's observed timestamp rather than request completion time."""
    return required_utc(event.timestamp, "collector timestamp")


def request_summary_payload(
    summary: RequestCostSummary, call_events: Sequence[UsageEvent]
) -> dict[str, Any]:
    """Nest summary metrics so legacy event consumers cannot double-count them."""
    call_input = sum(
        event.input_tokens + event.tool_context_tokens + event.embedding_tokens
        for event in call_events
    )
    call_output = sum(event.output_tokens for event in call_events)
    known_call_costs = [
        event.estimated_cost_usd
        for event in call_events
        if event.estimated_cost_usd is not None
    ]
    cost_is_unknown = len(known_call_costs) != len(call_events)
    call_cost = None if cost_is_unknown else sum(known_call_costs)
    cost_matches: bool | None
    if call_cost is None or summary.estimated_cost_usd is None:
        cost_matches = None
    else:
        cost_matches = isclose(call_cost, summary.estimated_cost_usd, abs_tol=1e-8)

    usage_complete = (
        summary.usage_coverage == 1.0
        and len(call_events) == summary.event_count
        and sum(event.llm_call_count for event in call_events) >= summary.llm_call_count
        and all(event.usage_source != "MISSING" for event in call_events)
    )
    zero_call = not call_events and summary.llm_call_count == 0 and summary.total_tokens == 0

    return {
        "attributionScope": "REQUEST_SUMMARY",
        "summary": {
            "outcome": summary.outcome,
            "totalTokens": summary.total_tokens,
            "inputTokens": summary.input_tokens,
            "outputTokens": summary.output_tokens,
            "embeddingTokens": summary.embedding_tokens,
            "estimatedCostUsd": summary.estimated_cost_usd,
            "reportedCostComplete": summary.cost_complete,
            "costComplete": (
                summary.cost_complete and usage_complete and not cost_is_unknown
                and (summary.estimated_cost_usd is not None or zero_call)
            ),
            "usageComplete": usage_complete,
            "usageCoverage": summary.usage_coverage,
            "llmCallCount": summary.llm_call_count,
            "collectorEventCount": summary.event_count,
            "knowledgeBackend": summary.knowledge_backend,
            "pricingVersion": summary.pricing_version,
            "elapsedMs": round(summary.elapsed_ms, 1),
        },
        "perCallReconciliation": {
            "collectorEventCount": len(call_events),
            "inputTokensMatch": call_input == summary.input_tokens,
            "outputTokensMatch": call_output == summary.output_tokens,
            "estimatedCostUsdMatch": cost_matches,
            "unknownCallCostPresent": cost_is_unknown,
        },
    }
