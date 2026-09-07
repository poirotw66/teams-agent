"""Cost summary queries for the AI Ops backoffice."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from agent_service.operations.access import ActorContext
from agent_service.usage import convert_usd_to_twd, list_model_rates_usd, lookup_rate

from .usage_projection import (
    UsageDimensions,
    confirmed_zero_call,
    known_cost_total,
    project_usage,
    usage_breakdown,
)


class CostsQueryMixin:
    """Mixin providing cost summary helpers for BackofficeQueryService."""

    async def costs_summary(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        model: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        all_events = await self._scoped_events(actor, period, force_refresh=force_refresh)
        usage_dimensions = UsageDimensions(all_events)
        events = list(project_usage(all_events).detail_events)
        model_filter = (model or "").strip()
        if model_filter:
            events = [
                event
                for event in events
                if str(event.payload.get("model") or "") == model_filter
            ]
        by_day: dict[str, float] = defaultdict(float)
        by_backend: Counter[str] = Counter()
        by_route_cost: dict[str, float] = defaultdict(float)
        by_issue_cost: dict[str, float] = defaultdict(float)
        input_tokens = 0
        output_tokens = 0
        embedding_tokens = 0
        tool_context_tokens = 0
        missing_cost_count = 0
        pricing_versions: Counter[str] = Counter()
        for event in events:
            day = event.occurred_at.date().isoformat()
            cost = event.payload.get("estimatedCostUsd")
            route, issue_type_id = usage_dimensions.resolve(event)
            if cost is None:
                if not confirmed_zero_call(event):
                    missing_cost_count += 1
            else:
                cost_value = float(cost)
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
        known_total = known_cost_total(events)
        exchange_rate = float(self._metrics.get("usdTwdExchangeRate", 31.70))
        by_model: list[dict[str, Any]] = []
        for item in usage_breakdown(events, "model"):
            input_count = int(item.get("inputTokens") or 0)
            output_count = int(item.get("outputTokens") or 0)
            rate = lookup_rate(str(item.get("model") or ""))
            by_model.append(
                {
                    **item,
                    "totalTokens": input_count + output_count,
                    "inputUsdPer1MTokens": rate[0] if rate else None,
                    "outputUsdPer1MTokens": rate[1] if rate else None,
                }
            )
        return {
            "periodDays": period.days,
            "periodPreset": period.preset,
            "model": model_filter or None,
            "totalEstimatedCostUsd": known_total,
            "totalEstimatedCostTwd": (
                convert_usd_to_twd(known_total, exchange_rate) if known_total is not None else None
            ),
            "usdTwdExchangeRate": exchange_rate,
            "missingCostEventCount": missing_cost_count,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "embeddingTokens": embedding_tokens,
            "toolContextTokens": tool_context_tokens,
            "llmCallCount": sum(int(event.payload.get("llmCallCount") or 0) for event in events),
            "byDay": [
                {"date": day, "estimatedCostUsd": round(value, 6)}
                for day, value in sorted(by_day.items())
            ],
            "byModel": by_model,
            "modelRates": list_model_rates_usd(),
            "byProvider": usage_breakdown(events, "provider"),
            "byComponent": usage_breakdown(events, "component"),
            "byBackend": [
                {"backend": backend, "eventCount": count}
                for backend, count in by_backend.most_common()
            ],
            "byRoute": [
                {"route": route, "estimatedCostUsd": round(value, 6)}
                for route, value in sorted(
                    by_route_cost.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "byIssueType": [
                {
                    "issueTypeId": issue_type_id,
                    "displayName": (
                        self.taxonomy.get(issue_type_id).display_name
                        if self.taxonomy.get(issue_type_id)
                        else issue_type_id
                    ),
                    "estimatedCostUsd": round(value, 6),
                }
                for issue_type_id, value in sorted(
                    by_issue_cost.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "eventCount": len(events),
            "pricingVersion": self._metrics.get("pricingVersion", "v1"),
            "pricingVersionsObserved": [
                {"pricingVersion": version, "eventCount": count}
                for version, count in pricing_versions.most_common()
            ],
        }

