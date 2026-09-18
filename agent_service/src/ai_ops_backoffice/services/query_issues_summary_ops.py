"""Pure helpers for issues summary and quality-seed assembly."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from operations_core.contracts import OperationalEvent
from operations_core.taxonomy import TaxonomyRepository

from .periods import ResolvedPeriod
from .usage_projection import UsageDimensions, project_usage

_ANSWER_EVENT_TYPES = frozenset({"answer.completed", "faq.answered", "knowledge.answered"})
_NO_ANSWER_RESULTS = frozenset({"NO_KNOWLEDGE", "FAILED"})


def previous_period_for(period: ResolvedPeriod) -> ResolvedPeriod:
    """Return the equal-length window immediately before ``period``."""
    duration = period.end_at - period.start_at
    return ResolvedPeriod(
        days=period.days,
        preset="custom",
        start_at=period.start_at - duration,
        end_at=period.start_at,
        explicit_range=True,
    )


def previous_extracted_counts(
    events: list[OperationalEvent],
) -> tuple[Counter[str], int]:
    extracted = [event for event in events if event.event_type == "issue.extracted"]
    counts = Counter(event.issue_type_id or "other.unclassified" for event in extracted)
    return counts, len(extracted)


def assemble_issues_summary_payload(
    *,
    period: ResolvedPeriod,
    taxonomy_version: str,
    total_count: int,
    prev_total: int,
    feedback_down: Counter[str],
    feedback_total: Counter[str],
    handoffs: Counter[str],
    no_answers: Counter[str],
    categories: list[str],
    items: list[dict[str, Any]],
    hierarchy: list[dict[str, Any]],
    trends: list[dict[str, Any]],
    query: str | None,
    owner_unit_id: str | None,
    unclassified_count: int,
) -> dict[str, Any]:
    return {
        "periodDays": period.days,
        "periodPreset": period.preset,
        "periodStart": period.start_at.isoformat(),
        "periodEnd": period.end_at.isoformat(),
        "taxonomyVersion": taxonomy_version,
        "totalCount": total_count,
        "previousTotalCount": prev_total,
        "totalChangeCount": total_count - prev_total,
        "totalChangeRate": total_change_rate(total_count, prev_total),
        "totalNegativeFeedbackCount": sum(feedback_down.values()),
        "totalFeedbackCount": sum(feedback_total.values()),
        "totalHandoffCount": sum(handoffs.values()),
        "totalNoAnswerCount": sum(no_answers.values()),
        "categories": categories,
        "items": items,
        "hierarchy": hierarchy,
        "trends": trends,
        "filterQuery": query,
        "filterOwnerUnitId": owner_unit_id,
        "unclassifiedCount": unclassified_count,
    }


def correlation_issue_map(events: list[OperationalEvent]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for event in events:
        if not event.correlation_id or not event.issue_type_id:
            continue
        if event.event_type in {"issue.extracted", "issue.classified"}:
            mapping[event.correlation_id] = event.issue_type_id
    return mapping


def resolve_issue_type_id(
    event: OperationalEvent,
    correlation_to_issue: dict[str, str],
) -> str:
    return event.issue_type_id or correlation_to_issue.get(event.correlation_id or "", "")


def collect_issue_quality_metrics(
    all_events: list[OperationalEvent],
    correlation_to_issue: dict[str, str],
) -> tuple[
    Counter[str],
    Counter[str],
    Counter[str],
    Counter[str],
    Counter[str],
    dict[str, float],
]:
    feedback_down: Counter[str] = Counter()
    feedback_up: Counter[str] = Counter()
    feedback_total: Counter[str] = Counter()
    handoffs: Counter[str] = Counter()
    no_answers: Counter[str] = Counter()
    costs: dict[str, float] = defaultdict(float)

    for event in all_events:
        issue_type_id = resolve_issue_type_id(event, correlation_to_issue)
        if not issue_type_id:
            continue
        if event.event_type == "feedback.recorded":
            feedback_total[issue_type_id] += 1
            rating = event.payload.get("rating")
            if rating == "DOWN":
                feedback_down[issue_type_id] += 1
            elif rating == "UP":
                feedback_up[issue_type_id] += 1
        if event.event_type.startswith("handoff."):
            handoffs[issue_type_id] += 1
        if (
            event.event_type in _ANSWER_EVENT_TYPES
            and event.payload.get("resultType") in _NO_ANSWER_RESULTS
        ):
            no_answers[issue_type_id] += 1

    usage_dimensions = UsageDimensions(all_events)
    for event in project_usage(all_events).detail_events:
        _, issue_type_id = usage_dimensions.resolve(event)
        cost = event.payload.get("estimatedCostUsd")
        if issue_type_id != "unknown" and cost is not None:
            costs[issue_type_id] += float(cost)

    return feedback_down, feedback_up, feedback_total, handoffs, no_answers, costs


def item_change_rate(count: int, previous_count: int, *, previous_total: int) -> float:
    if previous_count > 0:
        return round((count - previous_count) / previous_count, 4)
    if count > 0 and previous_total > 0:
        return 1.0
    return 0.0


def total_change_rate(total_count: int, previous_total: int) -> float:
    if previous_total > 0:
        return round((total_count - previous_total) / previous_total, 4)
    if total_count > 0:
        return 1.0
    return 0.0


def build_issue_summary_items(
    *,
    counts: Counter[str],
    prev_counts: Counter[str],
    prev_total: int,
    taxonomy: TaxonomyRepository,
    feedback_down: Counter[str],
    feedback_up: Counter[str],
    feedback_total: Counter[str],
    handoffs: Counter[str],
    no_answers: Counter[str],
    costs: dict[str, float],
) -> list[dict[str, Any]]:
    total = sum(counts.values()) or 1
    items: list[dict[str, Any]] = []
    for issue_type_id, count in counts.most_common():
        record = taxonomy.get(issue_type_id)
        prev_c = prev_counts.get(issue_type_id, 0)
        fb_total = feedback_total[issue_type_id]
        fb_down = feedback_down[issue_type_id]
        fb_up = feedback_up[issue_type_id]
        items.append(
            {
                "issueTypeId": issue_type_id,
                "displayName": record.display_name if record else issue_type_id,
                "parentIssueTypeId": record.parent_issue_type_id if record else None,
                "ownerUnitId": record.owner_unit_id if record else None,
                "description": record.description if record else "",
                "count": count,
                "previousCount": prev_c,
                "changeCount": count - prev_c,
                "changeRate": item_change_rate(count, prev_c, previous_total=prev_total),
                "share": round(count / total, 4),
                "feedbackCount": fb_total,
                "positiveFeedbackCount": fb_up,
                "negativeFeedbackCount": fb_down,
                "negativeFeedbackRate": round(fb_down / count, 4),
                "handoffCount": handoffs[issue_type_id],
                "handoffRate": round(handoffs[issue_type_id] / count, 4),
                "noAnswerCount": no_answers[issue_type_id],
                "noAnswerRate": round(no_answers[issue_type_id] / count, 4),
                "estimatedCostUsd": round(costs.get(issue_type_id, 0.0), 6),
            }
        )
    return items


def filter_issue_summary_items(
    items: list[dict[str, Any]],
    *,
    taxonomy: TaxonomyRepository,
    query: str | None,
    owner_unit_id: str | None,
) -> tuple[list[dict[str, Any]], set[str] | None]:
    matched_issue_ids: set[str] | None = None
    filtered = items
    if query:
        needle = query.casefold()
        filtered = [
            item
            for item in filtered
            if needle in item["issueTypeId"].casefold()
            or needle in item["displayName"].casefold()
            or (
                (rec := taxonomy.get(item["issueTypeId"])) is not None
                and needle in rec.description.casefold()
            )
        ]
        matched_issue_ids = {item["issueTypeId"] for item in filtered}

    if owner_unit_id:
        if owner_unit_id in {"other.unclassified", "unclassified"}:
            filtered = [
                item
                for item in filtered
                if item["issueTypeId"] == "other.unclassified" or not item.get("ownerUnitId")
            ]
        else:
            filtered = [item for item in filtered if item.get("ownerUnitId") == owner_unit_id]
        matched_issue_ids = {item["issueTypeId"] for item in filtered}

    return filtered, matched_issue_ids


def build_issue_day_trends(
    events: list[OperationalEvent],
    matched_issue_ids: set[str] | None,
) -> list[dict[str, Any]]:
    by_day: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        day = event.occurred_at.date().isoformat()
        by_day[day][event.issue_type_id or "other.unclassified"] += 1

    trends: list[dict[str, Any]] = []
    for day, day_counts in sorted(by_day.items()):
        day_items = [
            {"issueTypeId": issue_type_id, "count": issue_count}
            for issue_type_id, issue_count in day_counts.most_common()
            if matched_issue_ids is None or issue_type_id in matched_issue_ids
        ]
        if day_items:
            trends.append({"date": day, "counts": day_items})
    return trends


def build_quality_candidate_seed(
    event: OperationalEvent,
    *,
    issue_type_id: str,
    issue_type: Any,
) -> dict[str, Any] | None:
    case_type = None
    title = None
    description = ""
    if (
        event.event_type in _ANSWER_EVENT_TYPES
        and event.payload.get("resultType") in _NO_ANSWER_RESULTS
    ):
        case_type = "NO_ANSWER"
        title = f"{issue_type.display_name} 無答案"
        description = str(event.payload.get("answerMasked") or event.payload.get("resultType"))
    elif event.event_type == "issue.classified" and event.payload.get("confidenceStatus") == "LOW":
        case_type = "LOW_CONFIDENCE"
        title = f"{issue_type.display_name} 低信心分類"
        description = str(event.payload.get("normalizedDescription") or "LOW confidence")
    elif event.event_type == "feedback.recorded" and event.payload.get("rating") == "DOWN":
        case_type = "NEGATIVE_FEEDBACK"
        title = f"{issue_type.display_name} 負評"
        description = str(event.payload.get("reason") or "negative feedback")
    elif event.event_type.startswith("handoff."):
        case_type = "HANDOFF"
        title = f"{issue_type.display_name} 轉人工"
        description = str(event.payload.get("reason") or event.payload.get("status") or "handoff")
    if case_type is None:
        return None
    return {
        "source_type": "EVENT",
        "case_type": case_type,
        "title": title,
        "description": description,
        "issue_type_id": issue_type_id,
        "question_cluster_id": None,
        "owner_unit_id": issue_type.owner_unit_id,
        "source_event_ids": (event.event_id,),
        "conversation_refs": (event.conversation_id,) if event.conversation_id else (),
        "faq_ids": tuple(
            value for value in (event.payload.get("faqId"), event.payload.get("faqKey")) if value
        ),
        "document_ids": tuple(value for value in (event.payload.get("documentId"),) if value),
        "frequency": 1,
        "negative_rate": 1 if case_type == "NEGATIVE_FEEDBACK" else 0,
        "handoff_rate": 1 if case_type == "HANDOFF" else 0,
        "estimated_cost_impact": 0,
    }
