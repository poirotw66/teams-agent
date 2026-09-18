"""Cost aggregation helpers for costs_summary."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from operations_core.usage import convert_usd_to_twd, list_model_rates_usd, lookup_rate

from .usage_projection import (
    UsageDimensions,
    confirmed_zero_call,
    known_cost_total,
    usage_breakdown,
)


@dataclass
class CostAccumulators:
    by_day: dict[str, float]
    by_backend: Counter[str]
    by_route_cost: dict[str, float]
    by_issue_cost: dict[str, float]
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    tool_context_tokens: int
    missing_cost_count: int
    zero_cost_count: int
    estimated_cost_count: int
    pricing_versions: Counter[str]


def accumulate_cost_metrics(
    events: list[Any],
    usage_dimensions: UsageDimensions,
) -> CostAccumulators:
    by_day: dict[str, float] = defaultdict(float)
    by_backend: Counter[str] = Counter()
    by_route_cost: dict[str, float] = defaultdict(float)
    by_issue_cost: dict[str, float] = defaultdict(float)
    input_tokens = 0
    output_tokens = 0
    embedding_tokens = 0
    tool_context_tokens = 0
    missing_cost_count = 0
    zero_cost_count = 0
    estimated_cost_count = 0
    pricing_versions: Counter[str] = Counter()
    for event in events:
        day = event.occurred_at.date().isoformat()
        cost = event.payload.get("estimatedCostUsd")
        route, issue_type_id = usage_dimensions.resolve(event)
        if cost is None:
            if confirmed_zero_call(event):
                zero_cost_count += 1
            else:
                missing_cost_count += 1
        else:
            cost_value = float(cost)
            if cost_value == 0.0:
                zero_cost_count += 1
            else:
                estimated_cost_count += 1
            by_day[day] += cost_value
            by_route_cost[route] += cost_value
            by_issue_cost[issue_type_id] += cost_value
        backend = str(event.payload.get("knowledgeBackend") or "unknown")
        by_backend[backend] += 1
        input_tokens += int(event.payload.get("inputTokens") or 0)
        output_tokens += int(event.payload.get("outputTokens") or 0)
        embedding_tokens += int(event.payload.get("embeddingTokens") or 0)
        tool_context_tokens += int(event.payload.get("toolContextTokens") or 0)
        pricing_version = str(event.payload.get("pricingVersion") or "unknown")
        pricing_versions[pricing_version] += 1
    return CostAccumulators(
        by_day=by_day,
        by_backend=by_backend,
        by_route_cost=by_route_cost,
        by_issue_cost=by_issue_cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        embedding_tokens=embedding_tokens,
        tool_context_tokens=tool_context_tokens,
        missing_cost_count=missing_cost_count,
        zero_cost_count=zero_cost_count,
        estimated_cost_count=estimated_cost_count,
        pricing_versions=pricing_versions,
    )


def build_by_model_rows(events: list[Any], pricing_svc: Any) -> list[dict[str, Any]]:
    by_model: list[dict[str, Any]] = []
    for item in usage_breakdown(events, "model"):
        input_count = int(item.get("inputTokens") or 0)
        output_count = int(item.get("outputTokens") or 0)
        model_name = str(item.get("model") or "")
        rate = (
            pricing_svc.lookup_rate(model_name)
            if pricing_svc is not None
            else lookup_rate(model_name)
        )
        cost_val = item.get("estimatedCostUsd")
        if cost_val is not None:
            cost_status = "ZERO_COST" if float(cost_val) == 0.0 else "ESTIMATED"
        elif input_count == 0 and output_count == 0:
            cost_status = "ZERO_COST"
        else:
            cost_status = "UNKNOWN"
        by_model.append(
            {
                **item,
                "totalTokens": input_count + output_count,
                "costStatus": cost_status,
                "inputUsdPer1MTokens": rate[0] if rate else None,
                "outputUsdPer1MTokens": rate[1] if rate else None,
            }
        )
    return by_model


def resolve_pricing_context(
    *,
    pricing_svc: Any,
    metrics: dict[str, Any],
) -> tuple[float, list[Any], Any]:
    if pricing_svc is not None:
        return pricing_svc.get_exchange_rate(), pricing_svc.list_rates(), pricing_svc
    exchange_rate = float(metrics.get("usdTwdExchangeRate", 31.70))
    return exchange_rate, list_model_rates_usd(), None


def build_costs_summary_payload(
    *,
    taxonomy: Any,
    metrics: dict[str, Any],
    pricing_svc: Any,
    period: Any,
    events: list[Any],
    model_filter: str,
    acc: CostAccumulators,
) -> dict[str, Any]:
    known_total = known_cost_total(events)
    exchange_rate, model_rates, resolved_pricing = resolve_pricing_context(
        pricing_svc=pricing_svc,
        metrics=metrics,
    )
    by_model = build_by_model_rows(events, resolved_pricing)
    return {
        "periodDays": period.days,
        "periodPreset": period.preset,
        "model": model_filter or None,
        "totalEstimatedCostUsd": known_total,
        "totalEstimatedCostTwd": (
            convert_usd_to_twd(known_total, exchange_rate) if known_total is not None else None
        ),
        "usdTwdExchangeRate": exchange_rate,
        "estimatedCostEventCount": acc.estimated_cost_count,
        "zeroCostEventCount": acc.zero_cost_count,
        "missingCostEventCount": acc.missing_cost_count,
        "unknownCostEventCount": acc.missing_cost_count,
        "inputTokens": acc.input_tokens,
        "outputTokens": acc.output_tokens,
        "embeddingTokens": acc.embedding_tokens,
        "toolContextTokens": acc.tool_context_tokens,
        "llmCallCount": sum(int(event.payload.get("llmCallCount") or 0) for event in events),
        "byDay": [
            {"date": day, "estimatedCostUsd": round(value, 6)}
            for day, value in sorted(acc.by_day.items())
        ],
        "byModel": by_model,
        "modelRates": model_rates,
        "byProvider": usage_breakdown(events, "provider"),
        "byComponent": usage_breakdown(events, "component"),
        "byBackend": [
            {"backend": backend, "eventCount": count}
            for backend, count in acc.by_backend.most_common()
        ],
        "byRoute": [
            {"route": route, "estimatedCostUsd": round(value, 6)}
            for route, value in sorted(
                acc.by_route_cost.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        "byIssueType": [
            {
                "issueTypeId": issue_type_id,
                "displayName": (
                    taxonomy.get(issue_type_id).display_name
                    if taxonomy.get(issue_type_id)
                    else issue_type_id
                ),
                "estimatedCostUsd": round(value, 6),
            }
            for issue_type_id, value in sorted(
                acc.by_issue_cost.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
        "eventCount": len(events),
        "pricingVersion": metrics.get("pricingVersion", "v1"),
        "pricingVersionsObserved": [
            {"pricingVersion": version, "eventCount": count}
            for version, count in acc.pricing_versions.most_common()
        ],
    }
