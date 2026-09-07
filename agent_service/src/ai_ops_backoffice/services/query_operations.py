"""Operations summary and daily-aggregate queries for the AI Ops backoffice."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import (
    DEFAULT_TIMEZONE,
    METRICS_DEFINITION_VERSION,
    OperationalEvent,
    utc_now,
)
from agent_service.operations.scope import actor_bypasses_owner_unit_scope

from .daily_aggregates import (
    aggregate_store_updated_at,
    aggregates_are_fresh,
    aggregates_cover_period,
    materialize_daily_aggregates,
    summarize_aggregates,
)
from .query_math import percentile as _percentile
from .usage_projection import known_cost_total, project_usage


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
        if model:
            model_correlations = {
                event.correlation_id
                for event in events
                if event.correlation_id
                and event.event_type == "usage.recorded"
                and str(event.payload.get("model") or "") == model
            }
            events = [
                event
                for event in events
                if (event.correlation_id and event.correlation_id in model_correlations)
                or (event.event_type == "usage.recorded" and str(event.payload.get("model") or "") == model)
            ]
        if issue_type_id:
            issue_correlations = {
                event.correlation_id
                for event in events
                if event.correlation_id
                and event.issue_type_id == issue_type_id
            }
            events = [
                event
                for event in events
                if event.issue_type_id == issue_type_id
                or (event.correlation_id and event.correlation_id in issue_correlations)
            ]
        turns = [event for event in events if event.event_type == "turn.received"]
        issues = [event for event in events if event.event_type == "issue.extracted"]
        faq_hits = [event for event in events if event.event_type == "faq.answered"]
        knowledge_hits = [event for event in events if event.event_type == "knowledge.answered"]
        handoffs = [event for event in events if event.event_type.startswith("handoff.")]
        tickets = [event for event in events if event.event_type == "ticket.created"]
        feedback = [event for event in events if event.event_type == "feedback.recorded"]
        usage_projection = project_usage(events)
        usage_events = list(usage_projection.request_events)
        failed_requests = [event for event in events if event.event_type == "request.failed"]
        answer_events = [
            event
            for event in events
            if event.event_type in {"answer.completed", "faq.answered", "knowledge.answered"}
        ]
        conversations = {event.conversation_id for event in turns if event.conversation_id}
        actors = {event.actor_ref for event in turns if event.actor_ref}
        issue_types = Counter(
            event.issue_type_id or "other.unclassified"
            for event in issues
            if event.issue_type_id
        )
        cost_complete = sum(
            1
            for event in usage_events
            if event.payload.get("costComplete") is True
            or (
                event.payload.get("costComplete") is None
                and event.payload.get("estimatedCostUsd") is not None
            )
        )
        latencies = [
            float(event.payload["elapsedMs"])
            for event in usage_projection.request_latency_events
            if event.payload.get("elapsedMs") is not None
        ]
        total_tokens = sum(int(event.payload.get("totalTokens") or 0) for event in usage_events)
        no_answer_count = sum(
            1
            for event in answer_events
            if event.payload.get("resultType") in {"NO_KNOWLEDGE", "FAILED"}
        )
        clarification_count = sum(
            1
            for event in answer_events
            if event.payload.get("resultType") == "NEED_MORE_INFO"
        )
        resolved_count = sum(
            1 for event in feedback if event.payload.get("resolvedStatus") == "RESOLVED"
        )
        turn_count = len(turns) or 1
        latest_event_at = max((event.occurred_at for event in events), default=None)
        data_freshness_minutes = None
        data_delay_warning = None
        if latest_event_at is not None:
            freshness_delta = utc_now() - latest_event_at
            data_freshness_minutes = max(0, int(freshness_delta.total_seconds() // 60))
            if data_freshness_minutes > 15:
                data_delay_warning = (
                    f"Latest operational event in the selected period is "
                    f"{data_freshness_minutes} minutes old; this usually means "
                    "no recent traffic, not a batch pipeline failure."
                )

        metrics_source = "event_scan"
        turn_count_value = len(turns)
        issue_occurrence_count = len(issues)
        handoff_count = len(handoffs)
        top_issue_types = [
            {"issueTypeId": key, "count": value}
            for key, value in issue_types.most_common(5)
        ]
        estimated_cost = known_cost_total(usage_events)

        # Compute Trends by requested interval (DAY, WEEK, MONTH)
        def _trend_bucket(occurred_at: datetime) -> str:
            inv = (interval or "DAY").upper()
            if inv == "WEEK":
                year, week, _ = occurred_at.isocalendar()
                return f"{year}-W{week:02d}"
            if inv == "MONTH":
                return occurred_at.strftime("%Y-%m")
            return occurred_at.date().isoformat()

        bucket_turns: dict[str, list[OperationalEvent]] = defaultdict(list)
        bucket_issues: dict[str, list[OperationalEvent]] = defaultdict(list)
        bucket_usage: dict[str, list[OperationalEvent]] = defaultdict(list)

        for event in turns:
            bucket_turns[_trend_bucket(event.occurred_at)].append(event)
        for event in issues:
            bucket_issues[_trend_bucket(event.occurred_at)].append(event)
        for u_ev in usage_events:
            bucket_usage[_trend_bucket(u_ev.occurred_at)].append(u_ev)

        all_buckets = sorted(set(bucket_turns.keys()) | set(bucket_issues.keys()) | set(bucket_usage.keys()))
        trends = []
        for b_key in all_buckets:
            b_turn_events = bucket_turns[b_key]
            b_convs = {e.conversation_id for e in b_turn_events if e.conversation_id}
            b_actors = {e.actor_ref for e in b_turn_events if e.actor_ref}
            b_u_events = bucket_usage[b_key]
            b_cost = known_cost_total(b_u_events)
            b_tokens = sum(int(e.payload.get("totalTokens") or 0) for e in b_u_events)
            trends.append({
                "period": b_key,
                "conversationCount": len(b_convs),
                "turnCount": len(b_turn_events),
                "activeUserCount": len(b_actors),
                "issueOccurrenceCount": len(bucket_issues[b_key]),
                "totalTokens": b_tokens,
                "estimatedCostUsd": b_cost,
            })

        # Tenant-wide aggregates omit owner-unit slices. Overlaying them on a
        # scoped event scan would mix authorization boundaries in one report.
        # Rolling windows also stay on event_scan: whole-day rollups would
        # inflate the leading partial day. Aggregates apply only to fresh,
        # midnight-aligned explicit ranges for cross-unit actors.
        coverage_complete = False
        if not force_refresh and model is None and issue_type_id is None and self._actor_may_use_daily_aggregates(actor):
            aggregate_rows = self._aggregate_store.list_range(
                start_day=period.start_at.date().isoformat(),
                end_day=(period.end_at - timedelta(microseconds=1)).date().isoformat(),
                environment=self._environment,
            )
            if actor.tenant_id and actor.role not in {"SYSTEM_ADMIN", "AUDITOR"}:
                aggregate_rows = [
                    item
                    for item in aggregate_rows
                    if item.tenant_id in {"", actor.tenant_id}
                ]
            coverage_complete = aggregates_cover_period(
                aggregate_rows,
                start_at=period.start_at,
                end_at=period.end_at,
                environment=self._environment,
                explicit_range=period.explicit_range,
            )
            watermark = aggregate_store_updated_at(self._aggregate_store)
            if (
                coverage_complete
                and aggregate_rows
                and aggregates_are_fresh(updated_at=watermark)
            ):
                rolled = summarize_aggregates(aggregate_rows)
                metrics_source = "daily_aggregates"
                turn_count_value = int(rolled["turnCount"])
                issue_occurrence_count = int(rolled["issueOccurrenceCount"])
                handoff_count = int(rolled["handoffCount"])
                no_answer_count = int(rolled["noAnswerCount"])
                top_issue_types = rolled["topIssueTypes"]
                estimated_cost = float(rolled["estimatedCostUsd"])
            else:
                coverage_complete = False

        return {
            "periodDays": period.days,
            "periodPreset": period.preset,
            "periodStart": period.start_at.isoformat(),
            "periodEnd": period.end_at.isoformat(),
            "interval": (interval or "DAY").upper(),
            "trends": trends,
            "model": model,
            "issueTypeId": issue_type_id,
            "timezone": DEFAULT_TIMEZONE,
            "metricsDefinitionVersion": METRICS_DEFINITION_VERSION,
            "metricDefinitions": self._metrics.get("definitions", {}),
            "metricsSource": metrics_source,
            "aggregateCoverageComplete": coverage_complete,
            "updatedAt": utc_now().isoformat(),
            "latestEventAt": latest_event_at.isoformat() if latest_event_at else None,
            "dataFreshnessMinutes": data_freshness_minutes,
            "dataDelayWarning": data_delay_warning,
            "conversationCount": len(conversations),
            "turnCount": turn_count_value,
            "activeUserCount": len(actors),
            "issueOccurrenceCount": issue_occurrence_count,
            "topIssueTypes": top_issue_types,
            "faqAnswerCount": len(faq_hits),
            "knowledgeAnswerCount": len(knowledge_hits),
            "noAnswerCount": no_answer_count,
            "clarificationCount": clarification_count,
            "handoffCount": handoff_count,
            "ticketCount": len(tickets),
            "positiveFeedbackCount": sum(
                1 for event in feedback if event.payload.get("rating") == "UP"
            ),
            "negativeFeedbackCount": sum(
                1 for event in feedback if event.payload.get("rating") == "DOWN"
            ),
            "resolvedFeedbackCount": resolved_count,
            "totalTokens": total_tokens,
            "estimatedCostUsd": estimated_cost,
            "costCoverage": round(cost_complete / len(usage_events), 4) if usage_events else 0.0,
            "handoffRate": round(handoff_count / max(turn_count_value, 1), 4),
            "ticketRate": round(len(tickets) / turn_count, 4),
            "errorRate": round(len(failed_requests) / turn_count, 4),
            "p50LatencyMs": _percentile(latencies, 0.5),
            "p95LatencyMs": _percentile(latencies, 0.95),
            "requestFailureCount": len(failed_requests),
        }

