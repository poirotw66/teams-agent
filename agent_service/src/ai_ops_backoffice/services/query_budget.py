"""Domain query mixin: BudgetQueryMixin."""

from __future__ import annotations

from typing import Any

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import DEFAULT_TIMEZONE, METRICS_DEFINITION_VERSION
from agent_service.usage import convert_usd_to_twd
from collections import defaultdict
from zoneinfo import ZoneInfo

from .periods import ResolvedPeriod
from .usage_projection import confirmed_zero_call, known_cost_total, project_usage

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
        known_total = known_cost_total(usage_events) or 0.0
        if measure == "USD":
            actual_value = known_total
        elif measure == "TWD":
            actual_value = convert_usd_to_twd(
                known_total,
                float(self._metrics.get("usdTwdExchangeRate", 31.70)),
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
            "pricingVersion": self._metrics.get("pricingVersion", "v1"),
            "exchangeRateVersion": self._metrics.get(
                "exchangeRateVersion",
                self._metrics.get("metrics_definition_version", METRICS_DEFINITION_VERSION),
            ),
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

