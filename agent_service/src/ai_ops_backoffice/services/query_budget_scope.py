"""Budget scope filtering and measure computation helpers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from operations_core.usage import convert_usd_to_twd

from .usage_projection import confirmed_zero_call, known_cost_total


def governed_known_cost_usd(
    usage_events: list[Any],
    pricing_svc: Any | None,
    *,
    at: Any | None,
) -> float:
    """Prefer PricingService rates when available; otherwise use event estimates."""
    total = 0.0
    for event in usage_events:
        model = str(event.payload.get("model") or "")
        input_tokens = int(event.payload.get("inputTokens") or 0)
        output_tokens = int(event.payload.get("outputTokens") or 0)
        if pricing_svc is not None and model:
            rate = pricing_svc.lookup_rate(model, at=at)
            if rate is not None:
                total += (input_tokens * rate[0] + output_tokens * rate[1]) / 1_000_000
                continue
        estimated = event.payload.get("estimatedCostUsd")
        if estimated is not None:
            total += float(estimated)
        elif confirmed_zero_call(event):
            continue
    return total


def filter_events_for_budget_scope(
    scoped_events: list[Any],
    *,
    scope_type: str,
    scope_id: str,
) -> list[Any]:
    if scope_type == "PERSONAL":
        conversation_actors: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        for event in scoped_events:
            if event.actor_ref:
                conversation_actors[
                    (event.environment, event.tenant_id, event.conversation_id)
                ].add(event.actor_ref)
        return [
            event
            for event in scoped_events
            if event.actor_ref == scope_id
            or (
                not event.actor_ref
                and conversation_actors.get(
                    (event.environment, event.tenant_id, event.conversation_id)
                )
                == {scope_id}
            )
        ]
    if scope_type == "SERVICE":
        return [
            event
            for event in scoped_events
            if str(event.payload.get("serviceId") or "") == scope_id
        ]
    if scope_type == "TEAM":
        return [
            event for event in scoped_events if str(event.payload.get("teamId") or "") == scope_id
        ]
    if scope_type == "TENANT":
        return [event for event in scoped_events if event.tenant_id == scope_id]
    if scope_type == "MODEL":
        return [
            event
            for event in scoped_events
            if str(event.payload.get("model") or event.payload.get("modelId") or "") == scope_id
        ]
    if scope_type == "GLOBAL":
        return scoped_events
    raise ValueError(f"Unsupported budget scope: {scope_type}")


def compute_budget_measure(
    usage_events: list[Any],
    *,
    measure: str,
    pricing_svc: Any | None,
    pricing_at: Any,
    exchange_rate: float,
) -> tuple[float, float]:
    complete_cost_events = sum(
        1
        for event in usage_events
        if event.payload.get("estimatedCostUsd") is not None or confirmed_zero_call(event)
    )
    coverage = round(complete_cost_events / len(usage_events), 4) if usage_events else 1.0
    known_total = (
        governed_known_cost_usd(usage_events, pricing_svc, at=pricing_at)
        if measure in {"USD", "TWD"}
        else (known_cost_total(usage_events) or 0.0)
    )
    if measure == "USD":
        return known_total, coverage
    if measure == "TWD":
        return convert_usd_to_twd(known_total, exchange_rate), coverage
    if measure == "TOKEN":
        actual_value = float(
            sum(
                int(event.payload.get(key) or 0)
                for event in usage_events
                for key in (
                    "inputTokens",
                    "outputTokens",
                    "embeddingTokens",
                    "toolContextTokens",
                )
            )
        )
        return actual_value, 1.0
    if measure == "LLM_CALL_COUNT":
        actual_value = float(
            sum(int(event.payload.get("llmCallCount") or 0) for event in usage_events)
        )
        return actual_value, 1.0
    raise ValueError(f"Unsupported budget measure: {measure}")
