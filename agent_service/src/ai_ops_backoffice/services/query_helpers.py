"""Shared query helper functions used by domain query mixins."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent_service.operations.contracts import OperationalEvent
from agent_service.operations.taxonomy import TaxonomyRepository

def _is_published_knowledge_hit(event: OperationalEvent) -> bool:
    if event.payload.get("isDraft") is True:
        return False
    return bool(event.payload.get("releaseId"))


def _summarize_turn_events(
    turn_event: OperationalEvent,
    events: list[OperationalEvent],
) -> dict[str, Any]:
    related = [
        item
        for item in events
        if item.event_type != "turn.received"
        and item.correlation_id == turn_event.correlation_id
        and (not item.turn_id or item.turn_id == turn_event.turn_id)
    ]
    issue_type_id = next(
        (item.issue_type_id for item in related if item.issue_type_id),
        None,
    )
    route = next(
        (
            str(item.payload.get("route"))
            for item in related
            if item.event_type == "route.selected" and item.payload.get("route")
        ),
        None,
    )
    model = next(
        (
            str(item.payload.get("model"))
            for item in related
            if item.event_type == "usage.recorded" and item.payload.get("model")
        ),
        None,
    )
    result_type = next(
        (
            str(item.payload.get("resultType"))
            for item in related
            if item.event_type in {"answer.completed", "faq.answered", "knowledge.answered"}
            and item.payload.get("resultType")
        ),
        None,
    )
    answer_masked = next(
        (
            str(item.payload.get("answerMasked"))
            for item in related
            if item.event_type in {"answer.completed", "faq.answered", "knowledge.answered"}
            and item.payload.get("answerMasked")
        ),
        None,
    )
    faq_key = next(
        (
            str(item.payload.get("faqKey"))
            for item in related
            if item.event_type == "faq.answered" and item.payload.get("faqKey")
        ),
        None,
    )
    document_ids: list[str] = []
    release_ids: list[str] = []
    for item in related:
        if item.event_type not in {"knowledge.retrieved", "knowledge.answered"}:
            continue
        document_id = item.payload.get("documentId")
        if document_id and document_id not in document_ids:
            document_ids.append(str(document_id))
        release_id = item.payload.get("releaseId")
        if release_id and release_id not in release_ids:
            release_ids.append(str(release_id))
    latest_feedback = max(
        (item for item in related if item.event_type == "feedback.recorded"),
        key=lambda item: item.occurred_at,
        default=None,
    )
    feedback_rating = (
        str(latest_feedback.payload["rating"])
        if latest_feedback and latest_feedback.payload.get("rating")
        else None
    )
    handoff_status = next(
        (
            str(item.payload.get("status") or item.event_type)
            for item in related
            if item.event_type.startswith("handoff.")
        ),
        None,
    )
    resolved_status = (
        str(latest_feedback.payload["resolvedStatus"])
        if latest_feedback and latest_feedback.payload.get("resolvedStatus")
        else None
    )
    return {
        "issueTypeId": issue_type_id,
        "route": route,
        "model": model,
        "resultType": result_type,
        "answerMasked": answer_masked,
        "faqKey": faq_key,
        "documentIds": document_ids,
        "releaseIds": release_ids,
        "feedbackRating": feedback_rating,
        "resolvedStatus": resolved_status,
        "handoffStatus": handoff_status,
    }


def _build_issue_hierarchy(
    items: list[dict[str, Any]],
    taxonomy: TaxonomyRepository,
) -> list[dict[str, Any]]:
    counts = {item["issueTypeId"]: item for item in items}
    children_by_parent: dict[str | None, list[str]] = defaultdict(list)
    for record in taxonomy.list_active():
        children_by_parent[record.parent_issue_type_id].append(record.issue_type_id)

    def build_node(issue_type_id: str) -> dict[str, Any] | None:
        item = counts.get(issue_type_id)
        record = taxonomy.get(issue_type_id)
        child_nodes = [
            node
            for child_id in children_by_parent.get(issue_type_id, [])
            if (node := build_node(child_id)) is not None
        ]
        own_count = item["count"] if item else 0
        aggregate_count = own_count + sum(child["aggregateCount"] for child in child_nodes)
        if own_count == 0 and not child_nodes:
            return None
        return {
            "issueTypeId": issue_type_id,
            "displayName": record.display_name if record else issue_type_id,
            "parentIssueTypeId": record.parent_issue_type_id if record else None,
            "count": own_count,
            "aggregateCount": aggregate_count,
            "share": item["share"] if item else 0.0,
            "children": child_nodes,
        }

    hierarchy: list[dict[str, Any]] = []
    for record in taxonomy.list_active():
        if record.parent_issue_type_id is None:
            node = build_node(record.issue_type_id)
            if node is not None:
                hierarchy.append(node)
    if "other.unclassified" in counts:
        unclassified = counts["other.unclassified"]
        hierarchy.append(
            {
                "issueTypeId": "other.unclassified",
                "displayName": "Unclassified",
                "parentIssueTypeId": None,
                "count": unclassified["count"],
                "aggregateCount": unclassified["count"],
                "share": unclassified["share"],
                "children": [],
            }
        )
    return hierarchy



