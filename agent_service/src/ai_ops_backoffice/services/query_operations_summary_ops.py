"""Pure helpers for operations_summary assembly."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from operations_core.access import ActorContext
from operations_core.contracts import (
    DEFAULT_TIMEZONE,
    METRICS_DEFINITION_VERSION,
    OperationalEvent,
    utc_now,
)

from .daily_aggregates import (
    aggregate_store_updated_at,
    aggregates_are_fresh,
    aggregates_cover_period,
    summarize_aggregates,
)
from .periods import ResolvedPeriod
from .query_math import percentile as _percentile
from .usage_projection import known_cost_total, project_usage


def filter_events_by_model(
    events: list[OperationalEvent],
    model: str | None,
) -> list[OperationalEvent]:
    if not model:
        return events
    model_correlations = {
        event.correlation_id
        for event in events
        if event.correlation_id
        and event.event_type == "usage.recorded"
        and str(event.payload.get("model") or "") == model
    }
    return [
        event
        for event in events
        if (event.correlation_id and event.correlation_id in model_correlations)
        or (
            event.event_type == "usage.recorded"
            and str(event.payload.get("model") or "") == model
        )
    ]


def filter_events_by_issue_type(
    events: list[OperationalEvent],
    issue_type_id: str | None,
) -> list[OperationalEvent]:
    if not issue_type_id:
        return events
    issue_correlations = {
        event.correlation_id
        for event in events
        if event.correlation_id and event.issue_type_id == issue_type_id
    }
    return [
        event
        for event in events
        if event.issue_type_id == issue_type_id
        or (event.correlation_id and event.correlation_id in issue_correlations)
    ]


@dataclass(frozen=True)
class OperationsEventBuckets:
    turns: list[OperationalEvent]
    issues: list[OperationalEvent]
    faq_hits: list[OperationalEvent]
    knowledge_hits: list[OperationalEvent]
    handoffs: list[OperationalEvent]
    tickets: list[OperationalEvent]
    feedback: list[OperationalEvent]
    usage_events: list[OperationalEvent]
    failed_requests: list[OperationalEvent]
    answer_events: list[OperationalEvent]
    latencies: list[float]


def partition_operations_events(
    events: list[OperationalEvent],
) -> OperationsEventBuckets:
    usage_projection = project_usage(events)
    return OperationsEventBuckets(
        turns=[event for event in events if event.event_type == "turn.received"],
        issues=[event for event in events if event.event_type == "issue.extracted"],
        faq_hits=[event for event in events if event.event_type == "faq.answered"],
        knowledge_hits=[
            event for event in events if event.event_type == "knowledge.answered"
        ],
        handoffs=[
            event for event in events if event.event_type.startswith("handoff.")
        ],
        tickets=[event for event in events if event.event_type == "ticket.created"],
        feedback=[
            event for event in events if event.event_type == "feedback.recorded"
        ],
        usage_events=list(usage_projection.request_events),
        failed_requests=[
            event for event in events if event.event_type == "request.failed"
        ],
        answer_events=[
            event
            for event in events
            if event.event_type
            in {"answer.completed", "faq.answered", "knowledge.answered"}
        ],
        latencies=[
            float(event.payload["elapsedMs"])
            for event in usage_projection.request_latency_events
            if event.payload.get("elapsedMs") is not None
        ],
    )


@dataclass
class OperationsScanMetrics:
    conversations: set[str]
    actors: set[str]
    issue_types: Counter[str]
    cost_complete: int
    total_tokens: int
    no_answer_count: int
    clarification_count: int
    resolved_count: int
    turn_count: int
    latest_event_at: datetime | None
    turn_count_value: int
    issue_occurrence_count: int
    handoff_count: int
    top_issue_types: list[dict[str, Any]]
    estimated_cost: float


def compute_scan_metrics(
    events: list[OperationalEvent],
    buckets: OperationsEventBuckets,
) -> OperationsScanMetrics:
    conversations = {
        event.conversation_id for event in buckets.turns if event.conversation_id
    }
    actors = {event.actor_ref for event in buckets.turns if event.actor_ref}
    issue_types = Counter(
        event.issue_type_id or "other.unclassified"
        for event in buckets.issues
        if event.issue_type_id
    )
    cost_complete = sum(
        1
        for event in buckets.usage_events
        if event.payload.get("costComplete") is True
        or (
            event.payload.get("costComplete") is None
            and event.payload.get("estimatedCostUsd") is not None
        )
    )
    no_answer_count = sum(
        1
        for event in buckets.answer_events
        if event.payload.get("resultType") in {"NO_KNOWLEDGE", "FAILED"}
    )
    clarification_count = sum(
        1
        for event in buckets.answer_events
        if event.payload.get("resultType") == "NEED_MORE_INFO"
    )
    resolved_count = sum(
        1
        for event in buckets.feedback
        if event.payload.get("resolvedStatus") == "RESOLVED"
    )
    turn_count_value = len(buckets.turns)
    return OperationsScanMetrics(
        conversations=conversations,
        actors=actors,
        issue_types=issue_types,
        cost_complete=cost_complete,
        total_tokens=sum(
            int(event.payload.get("totalTokens") or 0) for event in buckets.usage_events
        ),
        no_answer_count=no_answer_count,
        clarification_count=clarification_count,
        resolved_count=resolved_count,
        turn_count=turn_count_value or 1,
        latest_event_at=max((event.occurred_at for event in events), default=None),
        turn_count_value=turn_count_value,
        issue_occurrence_count=len(buckets.issues),
        handoff_count=len(buckets.handoffs),
        top_issue_types=[
            {"issueTypeId": key, "count": value}
            for key, value in issue_types.most_common(5)
        ],
        estimated_cost=known_cost_total(buckets.usage_events),
    )


def trend_bucket_key(occurred_at: datetime, interval: str) -> str:
    inv = (interval or "DAY").upper()
    if inv == "WEEK":
        year, week, _ = occurred_at.isocalendar()
        return f"{year}-W{week:02d}"
    if inv == "MONTH":
        return occurred_at.strftime("%Y-%m")
    return occurred_at.date().isoformat()


def build_operations_trends(
    buckets: OperationsEventBuckets,
    *,
    interval: str,
) -> list[dict[str, Any]]:
    bucket_turns: dict[str, list[OperationalEvent]] = defaultdict(list)
    bucket_issues: dict[str, list[OperationalEvent]] = defaultdict(list)
    bucket_usage: dict[str, list[OperationalEvent]] = defaultdict(list)
    for event in buckets.turns:
        bucket_turns[trend_bucket_key(event.occurred_at, interval)].append(event)
    for event in buckets.issues:
        bucket_issues[trend_bucket_key(event.occurred_at, interval)].append(event)
    for usage_event in buckets.usage_events:
        bucket_usage[trend_bucket_key(usage_event.occurred_at, interval)].append(
            usage_event
        )
    all_buckets = sorted(
        set(bucket_turns) | set(bucket_issues) | set(bucket_usage)
    )
    trends: list[dict[str, Any]] = []
    for bucket_key in all_buckets:
        turn_events = bucket_turns[bucket_key]
        usage_events = bucket_usage[bucket_key]
        trends.append(
            {
                "period": bucket_key,
                "conversationCount": len(
                    {e.conversation_id for e in turn_events if e.conversation_id}
                ),
                "turnCount": len(turn_events),
                "activeUserCount": len(
                    {e.actor_ref for e in turn_events if e.actor_ref}
                ),
                "issueOccurrenceCount": len(bucket_issues[bucket_key]),
                "totalTokens": sum(
                    int(e.payload.get("totalTokens") or 0) for e in usage_events
                ),
                "estimatedCostUsd": known_cost_total(usage_events),
            }
        )
    return trends


@dataclass
class OperationsFreshness:
    data_freshness_minutes: int | None
    data_delay_warning: str | None
    freshness_meta: dict[str, Any] | None


def resolve_operations_freshness(
    *,
    tracker: Any | None,
    latest_event_at: datetime | None,
) -> OperationsFreshness:
    data_freshness_minutes = None
    data_delay_warning = None
    freshness_meta = None
    if tracker is not None:
        freshness_meta = tracker.compute_freshness(
            resource_type="operations_overview",
            watermark=None,
        ).model_dump(mode="json")
        lag_seconds = freshness_meta.get("lagSeconds")
        if lag_seconds is None:
            lag_seconds = freshness_meta.get("lag_seconds")
        if lag_seconds is not None:
            try:
                data_freshness_minutes = max(0, int(float(lag_seconds) // 60))
            except (TypeError, ValueError):
                data_freshness_minutes = None
        if freshness_meta.get("status") in {"STALE", "UNKNOWN", "DELAYED", "FAILED"}:
            data_delay_warning = (
                "Operations overview freshness is stale or unknown; "
                "pipeline sync/aggregation watermarks have not updated recently."
            )
    if data_freshness_minutes is None and latest_event_at is not None:
        freshness_delta = utc_now() - latest_event_at
        data_freshness_minutes = max(0, int(freshness_delta.total_seconds() // 60))
        if data_delay_warning is None and data_freshness_minutes > 15:
            data_delay_warning = (
                f"Latest operational event in the selected period is "
                f"{data_freshness_minutes} minutes old; this usually means "
                "no recent traffic, not a batch pipeline failure."
            )
    return OperationsFreshness(
        data_freshness_minutes=data_freshness_minutes,
        data_delay_warning=data_delay_warning,
        freshness_meta=freshness_meta,
    )


@dataclass
class AggregateOverlayResult:
    metrics_source: str
    coverage_complete: bool
    turn_count_value: int
    issue_occurrence_count: int
    handoff_count: int
    no_answer_count: int
    top_issue_types: list[dict[str, Any]]
    estimated_cost: float


def overlay_daily_aggregate_metrics(
    *,
    actor: ActorContext,
    period: ResolvedPeriod,
    aggregate_store: Any,
    environment: str,
    force_refresh: bool,
    model: str | None,
    issue_type_id: str | None,
    actor_may_use_daily_aggregates: bool,
    scan: OperationsScanMetrics,
) -> AggregateOverlayResult:
    result = AggregateOverlayResult(
        metrics_source="event_scan",
        coverage_complete=False,
        turn_count_value=scan.turn_count_value,
        issue_occurrence_count=scan.issue_occurrence_count,
        handoff_count=scan.handoff_count,
        no_answer_count=scan.no_answer_count,
        top_issue_types=scan.top_issue_types,
        estimated_cost=scan.estimated_cost,
    )
    if force_refresh or model is not None or issue_type_id is not None:
        return result
    if not actor_may_use_daily_aggregates:
        return result
    aggregate_rows = aggregate_store.list_range(
        start_day=period.start_at.date().isoformat(),
        end_day=(period.end_at - timedelta(microseconds=1)).date().isoformat(),
        environment=environment,
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
        environment=environment,
        explicit_range=period.explicit_range,
    )
    watermark = aggregate_store_updated_at(aggregate_store)
    if (
        coverage_complete
        and aggregate_rows
        and aggregates_are_fresh(updated_at=watermark)
    ):
        rolled = summarize_aggregates(aggregate_rows)
        return AggregateOverlayResult(
            metrics_source="daily_aggregates",
            coverage_complete=True,
            turn_count_value=int(rolled["turnCount"]),
            issue_occurrence_count=int(rolled["issueOccurrenceCount"]),
            handoff_count=int(rolled["handoffCount"]),
            no_answer_count=int(rolled["noAnswerCount"]),
            top_issue_types=rolled["topIssueTypes"],
            estimated_cost=float(rolled["estimatedCostUsd"]),
        )
    return result


def assemble_operations_summary_payload(
    *,
    period: ResolvedPeriod,
    interval: str,
    model: str | None,
    issue_type_id: str | None,
    buckets: OperationsEventBuckets,
    scan: OperationsScanMetrics,
    freshness: OperationsFreshness,
    overlay: AggregateOverlayResult,
    trends: list[dict[str, Any]],
    metric_definitions: dict[str, Any],
) -> dict[str, Any]:
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
        "metricDefinitions": metric_definitions,
        "metricsSource": overlay.metrics_source,
        "aggregateCoverageComplete": overlay.coverage_complete,
        "updatedAt": utc_now().isoformat(),
        "latestEventAt": (
            scan.latest_event_at.isoformat() if scan.latest_event_at else None
        ),
        "dataFreshnessMinutes": freshness.data_freshness_minutes,
        "dataDelayWarning": freshness.data_delay_warning,
        "freshness": freshness.freshness_meta,
        "conversationCount": len(scan.conversations),
        "turnCount": overlay.turn_count_value,
        "activeUserCount": len(scan.actors),
        "issueOccurrenceCount": overlay.issue_occurrence_count,
        "topIssueTypes": overlay.top_issue_types,
        "faqAnswerCount": len(buckets.faq_hits),
        "knowledgeAnswerCount": len(buckets.knowledge_hits),
        "noAnswerCount": overlay.no_answer_count,
        "clarificationCount": scan.clarification_count,
        "handoffCount": overlay.handoff_count,
        "ticketCount": len(buckets.tickets),
        "positiveFeedbackCount": sum(
            1 for event in buckets.feedback if event.payload.get("rating") == "UP"
        ),
        "negativeFeedbackCount": sum(
            1 for event in buckets.feedback if event.payload.get("rating") == "DOWN"
        ),
        "resolvedFeedbackCount": scan.resolved_count,
        "totalTokens": scan.total_tokens,
        "estimatedCostUsd": overlay.estimated_cost,
        "costCoverage": (
            round(scan.cost_complete / len(buckets.usage_events), 4)
            if buckets.usage_events
            else 0.0
        ),
        "handoffRate": round(overlay.handoff_count / max(overlay.turn_count_value, 1), 4),
        "ticketRate": round(len(buckets.tickets) / scan.turn_count, 4),
        "errorRate": round(len(buckets.failed_requests) / scan.turn_count, 4),
        "p50LatencyMs": _percentile(buckets.latencies, 0.5),
        "p95LatencyMs": _percentile(buckets.latencies, 0.95),
        "requestFailureCount": len(buckets.failed_requests),
    }
