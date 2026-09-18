"""Shared query helper functions used by domain query mixins."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from operations_core.contracts import OperationalEvent
from operations_core.taxonomy import TaxonomyRepository

from .query_turn_summary import summarize_turn_events


def _is_published_knowledge_hit(event: OperationalEvent) -> bool:
    if event.payload.get("isDraft") is True:
        return False
    return bool(event.payload.get("releaseId"))


def _summarize_turn_events(
    turn_event: OperationalEvent,
    events: list[OperationalEvent],
) -> dict[str, Any]:
    return summarize_turn_events(turn_event, events)


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
