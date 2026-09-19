"""Operations summary and daily-aggregate queries for the AI Ops backoffice."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from operations_core.access import ActorContext
from operations_core.scope import actor_bypasses_owner_unit_scope

from .daily_aggregates import (
    aggregates_cover_period,
    materialize_daily_aggregates,
    summarize_aggregates,
)
from .query_operations_summary_ops import (
    assemble_operations_summary_payload,
    build_operations_trends,
    compute_scan_metrics,
    filter_events_by_issue_type,
    filter_events_by_model,
    overlay_daily_aggregate_metrics,
    partition_operations_events,
    resolve_operations_freshness,
)

__all__ = [
    "OperationsQueryMixin",
    "OperationsQueryService",
]


class OperationsQueryMixin:
    """Domain query helpers mixed into BackofficeQueryService."""

    async def rebuild_daily_aggregates(self, *, days: int = 30) -> dict[str, Any]:
        """Materialize daily aggregates from operational events (worker entrypoint)."""
        period = self._resolve_period(days=days)
        events = await self._events(period=period, force_refresh=True)
        return materialize_daily_aggregates(
            events,
            self._aggregate_store,
            start_at=period.start_at,
            end_at=period.end_at,
            environment=self._environment,
        )

    def _actor_may_use_daily_aggregates(self, actor: ActorContext) -> bool:
        """Aggregates are tenant-wide and omit owner-unit dimensions.

        Until the read model carries authorizable owner-unit slices, only
        cross-unit roles may consume aggregate rollups. Scoped BU actors stay
        on ``operations_summary`` event scans.
        """
        return actor_bypasses_owner_unit_scope(actor)

    async def daily_aggregates_summary(
        self,
        actor: ActorContext,
        *,
        days: int = 7,
    ) -> dict[str, Any]:
        period = self._resolve_period(days=days)
        if not self._actor_may_use_daily_aggregates(actor):
            return {
                "source": "unavailable_for_scoped_actor",
                "dayCount": 0,
                "turnCount": 0,
                "issueOccurrenceCount": 0,
                "handoffCount": 0,
                "feedbackCount": 0,
                "noAnswerCount": 0,
                "estimatedCostUsd": 0.0,
                "topIssueTypes": [],
                "periodDays": period.days,
                "periodStart": period.start_at.isoformat(),
                "periodEnd": period.end_at.isoformat(),
                "coverageComplete": False,
                "items": [],
                "reason": (
                    "Daily aggregates omit owner-unit dimensions; "
                    "scoped actors must use operations_summary event scan."
                ),
            }
        rows = self._aggregate_store.list_range(
            start_day=period.start_at.date().isoformat(),
            end_day=(period.end_at - timedelta(microseconds=1)).date().isoformat(),
            environment=self._environment,
        )
        if actor.tenant_id and actor.role not in {"SYSTEM_ADMIN", "AUDITOR"}:
            rows = [item for item in rows if item.tenant_id in {"", actor.tenant_id}]
        covered = aggregates_cover_period(
            rows,
            start_at=period.start_at,
            end_at=period.end_at,
            environment=self._environment,
            explicit_range=period.explicit_range,
        )
        summary = summarize_aggregates(rows)
        return {
            **summary,
            "periodDays": period.days,
            "periodStart": period.start_at.isoformat(),
            "periodEnd": period.end_at.isoformat(),
            "coverageComplete": covered,
            "items": [item.as_dict() for item in rows],
        }

    async def operations_summary(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 7,
        start_date: str | None = None,
        end_date: str | None = None,
        model: str | None = None,
        issue_type_id: str | None = None,
        interval: str = "DAY",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        events = await self._scoped_events(actor, period, force_refresh=force_refresh)
        events = filter_events_by_model(events, model)
        events = filter_events_by_issue_type(events, issue_type_id)
        buckets = partition_operations_events(events)
        scan = compute_scan_metrics(events, buckets)
        freshness = resolve_operations_freshness(
            tracker=getattr(self, "_freshness_tracker", None),
            latest_event_at=scan.latest_event_at,
        )
        trends = build_operations_trends(buckets, interval=interval)
        # Tenant-wide aggregates omit owner-unit slices. Overlaying them on a
        # scoped event scan would mix authorization boundaries in one report.
        # Rolling windows also stay on event_scan: whole-day rollups would
        # inflate the leading partial day. Aggregates apply only to fresh,
        # midnight-aligned explicit ranges for cross-unit actors.
        overlay = overlay_daily_aggregate_metrics(
            actor=actor,
            period=period,
            aggregate_store=self._aggregate_store,
            environment=self._environment,
            force_refresh=force_refresh,
            model=model,
            issue_type_id=issue_type_id,
            actor_may_use_daily_aggregates=self._actor_may_use_daily_aggregates(actor),
            scan=scan,
        )
        return assemble_operations_summary_payload(
            period=period,
            interval=interval,
            model=model,
            issue_type_id=issue_type_id,
            buckets=buckets,
            scan=scan,
            freshness=freshness,
            overlay=overlay,
            trends=trends,
            metric_definitions=self._metrics.get("definitions", {}),
        )


OperationsQueryService = OperationsQueryMixin

