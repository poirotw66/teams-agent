from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from agent_service.operations.access import ActorContext

from .periods import ResolvedPeriod, resolve_period
from .query_service import BackofficeQueryService
from .usage_projection import UsageDimensions, confirmed_zero_call, known_cost_total, project_usage


def _check(name: str, expected: float | None, actual: float | None) -> dict[str, Any]:
    return {
        "name": name,
        "fromEvents": expected,
        "fromSummary": actual,
        "match": expected == actual,
    }


async def reconcile_operations_summary(
    query_service: BackofficeQueryService,
    actor: ActorContext,
    *,
    preset: str | None = None,
    days: int = 7,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    period: ResolvedPeriod = resolve_period(
        preset=preset,
        days=days,
        start_date=start_date,
        end_date=end_date,
    )
    events = await query_service._scoped_events(actor, period)
    summary = await query_service.operations_summary(
        actor,
        preset=preset,
        days=days,
        start_date=start_date,
        end_date=end_date,
    )

    turns = [event for event in events if event.event_type == "turn.received"]
    issues = [event for event in events if event.event_type == "issue.extracted"]
    usage_events = project_usage(events).request_events
    feedback = [event for event in events if event.event_type == "feedback.recorded"]
    conversations = {event.conversation_id for event in turns if event.conversation_id}
    actors = {event.actor_ref for event in turns if event.actor_ref}
    cost_complete = sum(1 for event in usage_events if event.payload.get("costComplete"))

    checks = [
        _check("conversationCount", len(conversations), summary["conversationCount"]),
        _check("turnCount", len(turns), summary["turnCount"]),
        _check("activeUserCount", len(actors), summary["activeUserCount"]),
        _check("issueOccurrenceCount", len(issues), summary["issueOccurrenceCount"]),
        _check(
            "positiveFeedbackCount",
            sum(1 for event in feedback if event.payload.get("rating") == "UP"),
            summary["positiveFeedbackCount"],
        ),
        _check(
            "negativeFeedbackCount",
            sum(1 for event in feedback if event.payload.get("rating") == "DOWN"),
            summary["negativeFeedbackCount"],
        ),
        _check(
            "estimatedCostUsd",
            known_cost_total(usage_events),
            summary["estimatedCostUsd"],
        ),
    ]
    if usage_events:
        coverage_from_events = round(cost_complete / len(usage_events), 4)
        checks.append(
            _check("costCoverage", coverage_from_events, summary["costCoverage"]),
        )

    duplicate_event_ids = [
        event_id
        for event_id, count in Counter(event.event_id for event in events).items()
        if count > 1
    ]

    return {
        "periodPreset": period.preset,
        "periodStart": period.start_at.isoformat(),
        "periodEnd": period.end_at.isoformat(),
        "eventCount": len(events),
        "duplicateEventIds": duplicate_event_ids,
        "checks": checks,
        "allMatch": all(item["match"] for item in checks) and not duplicate_event_ids,
    }


async def reconcile_costs_summary(
    query_service: BackofficeQueryService,
    actor: ActorContext,
    *,
    preset: str | None = None,
    days: int = 7,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    period: ResolvedPeriod = resolve_period(
        preset=preset,
        days=days,
        start_date=start_date,
        end_date=end_date,
    )
    events = await query_service._scoped_events(actor, period)
    summary = await query_service.costs_summary(
        actor,
        preset=preset,
        days=days,
        start_date=start_date,
        end_date=end_date,
    )
    usage_events = project_usage(events).detail_events
    usage_dimensions = UsageDimensions(events)
    by_route: dict[str, float] = defaultdict(float)
    by_issue: dict[str, float] = defaultdict(float)
    for event in usage_events:
        cost = event.payload.get("estimatedCostUsd")
        if cost is None:
            continue
        route, issue_type = usage_dimensions.resolve(event)
        by_route[route] += float(cost)
        by_issue[issue_type] += float(cost)

    checks = [
        _check("totalEstimatedCostUsd", known_cost_total(usage_events), summary["totalEstimatedCostUsd"]),
        _check("missingCostEventCount", sum(
            event.payload.get("estimatedCostUsd") is None and not confirmed_zero_call(event)
            for event in usage_events
        ), summary["missingCostEventCount"]),
    ]
    for route_item in summary.get("byRoute", []):
        route = str(route_item["route"])
        checks.append(
            _check(
                f"byRoute.{route}",
                round(by_route.get(route, 0.0), 6),
                route_item["estimatedCostUsd"],
            )
        )
    for issue_item in summary.get("byIssueType", []):
        issue_type_id = str(issue_item["issueTypeId"])
        checks.append(
            _check(
                f"byIssueType.{issue_type_id}",
                round(by_issue.get(issue_type_id, 0.0), 6),
                issue_item["estimatedCostUsd"],
            )
        )

    return {
        "periodPreset": period.preset,
        "periodStart": period.start_at.isoformat(),
        "periodEnd": period.end_at.isoformat(),
        "eventCount": len(events),
        "usageEventCount": len(usage_events),
        "checks": checks,
        "allMatch": all(item["match"] for item in checks),
    }


async def reconcile_issues_summary(
    query_service: BackofficeQueryService,
    actor: ActorContext,
    *,
    preset: str | None = None,
    days: int = 7,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    period: ResolvedPeriod = resolve_period(
        preset=preset,
        days=days,
        start_date=start_date,
        end_date=end_date,
    )
    events = await query_service._scoped_events(actor, period)
    summary = await query_service.issues_summary(
        actor,
        preset=preset,
        days=days,
        start_date=start_date,
        end_date=end_date,
    )
    issues = [event for event in events if event.event_type == "issue.extracted"]
    counts = Counter(event.issue_type_id or "other.unclassified" for event in issues)
    total = sum(counts.values()) or 1
    checks = [
        _check("totalIssueCount", len(issues), sum(item["count"] for item in summary["items"])),
        _check(
            "unclassifiedCount",
            counts.get("other.unclassified", 0),
            summary["unclassifiedCount"],
        ),
    ]
    for item in summary["items"]:
        issue_type_id = str(item["issueTypeId"])
        expected_share = round(counts.get(issue_type_id, 0) / total, 4)
        checks.append(
            _check(f"issueCount.{issue_type_id}", counts.get(issue_type_id, 0), item["count"])
        )
        checks.append(
            _check(f"issueShare.{issue_type_id}", expected_share, item["share"])
        )

    return {
        "periodPreset": period.preset,
        "periodStart": period.start_at.isoformat(),
        "periodEnd": period.end_at.isoformat(),
        "eventCount": len(events),
        "issueOccurrenceCount": len(issues),
        "checks": checks,
        "allMatch": all(item["match"] for item in checks),
    }
