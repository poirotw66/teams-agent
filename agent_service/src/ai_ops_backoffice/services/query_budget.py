"""Domain query mixin: BudgetQueryMixin."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import DEFAULT_TIMEZONE
from agent_service.usage import convert_usd_to_twd
from zoneinfo import ZoneInfo

from .periods import ResolvedPeriod
from .usage_projection import confirmed_zero_call, known_cost_total, project_usage


def _governed_known_cost_usd(
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


class BudgetQueryMixin:
    async def budget_usage(
        self,
        actor: ActorContext,
        *,
        scope_type: str,
        scope_id: str,
        period_type: str,
        measure: str,
    ) -> dict[str, Any]:
        period = self._resolve_period(preset="today" if period_type == "DAILY" else "month")
        scoped_events = await self._scoped_events(actor, period)
        if scope_type == "PERSONAL":
            conversation_actors: dict[tuple[str, str, str], set[str]] = defaultdict(set)
            for event in scoped_events:
                if event.actor_ref:
                    conversation_actors[
                        (event.environment, event.tenant_id, event.conversation_id)
                    ].add(event.actor_ref)
            scoped_events = [
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
        elif scope_type == "SERVICE":
            scoped_events = [
                event
                for event in scoped_events
                if str(event.payload.get("serviceId") or "") == scope_id
            ]
        elif scope_type == "TEAM":
            scoped_events = [
                event
                for event in scoped_events
                if str(event.payload.get("teamId") or "") == scope_id
            ]
        elif scope_type == "TENANT":
            scoped_events = [event for event in scoped_events if event.tenant_id == scope_id]
        elif scope_type == "MODEL":
            scoped_events = [
                event
                for event in scoped_events
                if str(event.payload.get("model") or event.payload.get("modelId") or "") == scope_id
            ]
        elif scope_type != "GLOBAL":
            raise ValueError(f"Unsupported budget scope: {scope_type}")
        usage_events = list(project_usage(scoped_events).detail_events)
        complete_cost_events = sum(
            1
            for event in usage_events
            if event.payload.get("estimatedCostUsd") is not None or confirmed_zero_call(event)
        )
        coverage = (
            round(complete_cost_events / len(usage_events), 4) if usage_events else 1.0
        )
        pricing_svc = getattr(self, "_pricing_service", None)
        pricing_at = period.end_at
        exchange_rate = (
            pricing_svc.get_exchange_rate(at=pricing_at)
            if pricing_svc is not None
            else float(self._metrics.get("usdTwdExchangeRate", 31.70))
        )
        pricing_version = (
            pricing_svc.get_pricing_version(at=pricing_at)
            if pricing_svc is not None
            else str(self._metrics.get("pricingVersion", "v1"))
        )
        # FX is versioned with the same HistoricalPricingRule stamp.
        exchange_rate_version = pricing_version
        known_total = (
            _governed_known_cost_usd(usage_events, pricing_svc, at=pricing_at)
            if measure in {"USD", "TWD"}
            else (known_cost_total(usage_events) or 0.0)
        )
        if measure == "USD":
            actual_value = known_total
        elif measure == "TWD":
            actual_value = convert_usd_to_twd(
                known_total,
                exchange_rate,
            )
        elif measure == "TOKEN":
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
            coverage = 1.0
        elif measure == "LLM_CALL_COUNT":
            actual_value = float(
                sum(int(event.payload.get("llmCallCount") or 0) for event in usage_events)
            )
            coverage = 1.0
        else:
            raise ValueError(f"Unsupported budget measure: {measure}")
        local_start = (
            period.start_at.astimezone(ZoneInfo(DEFAULT_TIMEZONE))
            if period.start_at.tzinfo
            else period.start_at
        )
        return {
            "actualValue": round(actual_value, 6),
            "coverage": coverage,
            "periodKey": local_start.strftime(
                "%Y-%m-%d" if period_type == "DAILY" else "%Y-%m"
            ),
            "pricingVersion": pricing_version,
            "exchangeRateVersion": exchange_rate_version,
        }

    async def list_active_actors_for_budget(
        self,
        actor: ActorContext,
        period: ResolvedPeriod,
    ) -> list[str]:
        scoped_events = await self._scoped_events(actor, period)
        actors: set[str] = set()
        for event in scoped_events:
            if event.actor_ref:
                actors.add(event.actor_ref)
        return sorted(actors)
