"""Cost summary queries for the AI Ops backoffice."""

from __future__ import annotations

from typing import Any

from operations_core.access import ActorContext

from .query_costs_aggregate import accumulate_cost_metrics, build_costs_summary_payload
from .usage_projection import UsageDimensions, project_usage


def _cost_event_is_relevant(payload: dict) -> bool:
    """Drop empty seed/replay summaries that only inflate an unknown model row."""
    if int(payload.get("totalTokens") or 0) > 0:
        return True
    if int(payload.get("inputTokens") or 0) > 0 or int(payload.get("outputTokens") or 0) > 0:
        return True
    if int(payload.get("llmCallCount") or 0) > 0:
        return True
    cost = payload.get("estimatedCostUsd")
    if cost is None:
        return False
    return float(cost) != 0.0


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
        events = [
            event
            for event in project_usage(all_events).detail_events
            if _cost_event_is_relevant(event.payload)
        ]
        model_filter = (model or "").strip()
        if model_filter:
            events = [
                event for event in events if str(event.payload.get("model") or "") == model_filter
            ]
        acc = accumulate_cost_metrics(events, usage_dimensions)
        return build_costs_summary_payload(
            taxonomy=self.taxonomy,
            metrics=self._metrics,
            pricing_svc=getattr(self, "pricing_service", None),
            period=period,
            events=events,
            model_filter=model_filter,
            acc=acc,
        )
