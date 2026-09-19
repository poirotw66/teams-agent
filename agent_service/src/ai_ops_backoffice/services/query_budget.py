"""Domain query mixin: BudgetQueryMixin."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from operations_core.access import ActorContext
from operations_core.contracts import DEFAULT_TIMEZONE

from .periods import ResolvedPeriod
from .query_budget_scope import compute_budget_measure, filter_events_for_budget_scope
from .usage_projection import project_usage

__all__ = [
    "BudgetQueryMixin",
    "BudgetQueryService",
]


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
        scoped_events = filter_events_for_budget_scope(
            scoped_events, scope_type=scope_type, scope_id=scope_id
        )
        usage_events = list(project_usage(scoped_events).detail_events)
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
        actual_value, coverage = compute_budget_measure(
            usage_events,
            measure=measure,
            pricing_svc=pricing_svc,
            pricing_at=pricing_at,
            exchange_rate=exchange_rate,
        )
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
            "exchangeRateVersion": pricing_version,
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


BudgetQueryService = BudgetQueryMixin

