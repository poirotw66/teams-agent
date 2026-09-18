"""Pure assembly helpers for knowledge performance and inventory payloads."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

from operations_core.contracts import OperationalEvent
from operations_core.taxonomy import TaxonomyRepository

from .query_helpers import _is_published_knowledge_hit
from .query_knowledge_status import normalize_format_type


def document_hit_events(
    events: list[OperationalEvent],
    document_id: str,
) -> list[OperationalEvent]:
    return [
        event
        for event in events
        if event.event_type in {"knowledge.retrieved", "knowledge.answered"}
        and _is_published_knowledge_hit(event)
        and (
            event.payload.get("documentId") == document_id
            or any(
                citation.get("documentId") == document_id
                for citation in (event.payload.get("citations") or [])
                if isinstance(citation, dict)
            )
        )
    ]


def matching_feedback_events(
    events: list[OperationalEvent],
    *,
    hit_conversations: set[str],
    hit_correlations: set[str],
    hit_turns: set[str],
) -> list[OperationalEvent]:
    return [
        event
        for event in events
        if event.event_type == "feedback.recorded"
        and (
            (event.correlation_id and event.correlation_id in hit_correlations)
            or (event.turn_id and event.turn_id in hit_turns)
            or (
                not event.correlation_id
                and not event.turn_id
                and event.conversation_id in hit_conversations
            )
        )
    ]


def _issue_distribution(
    issue_counts: Counter[str],
    taxonomy: TaxonomyRepository,
) -> list[dict[str, Any]]:
    items = []
    for itype_id, count in issue_counts.most_common():
        record = taxonomy.get(itype_id)
        items.append(
            {
                "issueTypeId": itype_id,
                "displayName": record.display_name if record else itype_id,
                "count": count,
            }
        )
    return items


def _serialize_hit_record(
    event: OperationalEvent,
    taxonomy: TaxonomyRepository,
) -> dict[str, Any]:
    return {
        "occurredAt": event.occurred_at.isoformat(),
        "conversationId": event.conversation_id,
        "correlationId": event.correlation_id,
        "turnId": event.turn_id,
        "chunkId": event.payload.get("chunkId"),
        "releaseId": event.payload.get("releaseId"),
        "issueTypeId": event.issue_type_id,
        "issueTypeDisplayName": (
            taxonomy.get(event.issue_type_id).display_name
            if event.issue_type_id and taxonomy.get(event.issue_type_id)
            else event.issue_type_id
        ),
    }


def _paginate_hits(
    all_hits: list[OperationalEvent],
    *,
    issue_type_id: str | None,
    limit: int,
    cursor: str | None,
    taxonomy: TaxonomyRepository,
) -> tuple[list[OperationalEvent], list[dict[str, Any]], int, str | None]:
    filtered_hits = (
        [hit for hit in all_hits if hit.issue_type_id == issue_type_id]
        if issue_type_id
        else all_hits
    )
    sorted_hits = sorted(filtered_hits, key=lambda item: item.occurred_at, reverse=True)
    start_idx = int(cursor) if cursor and cursor.isdigit() else 0
    page_hits = sorted_hits[start_idx : start_idx + limit]
    next_cursor = (
        str(start_idx + len(page_hits))
        if start_idx + len(page_hits) < len(sorted_hits)
        else None
    )
    hit_records = [_serialize_hit_record(event, taxonomy) for event in page_hits]
    return filtered_hits, hit_records, start_idx, next_cursor


def build_document_performance_payload(
    *,
    document_id: str,
    period: Any,
    events: list[OperationalEvent],
    taxonomy: TaxonomyRepository,
    issue_type_id: str | None,
    limit: int,
    cursor: str | None,
    governance: dict[str, Any],
) -> dict[str, Any]:
    all_hits = document_hit_events(events, document_id)
    hit_conversations = {event.conversation_id for event in all_hits if event.conversation_id}
    hit_correlations = {event.correlation_id for event in all_hits if event.correlation_id}
    hit_turns = {event.turn_id for event in all_hits if event.turn_id}
    feedback_events = matching_feedback_events(
        events,
        hit_conversations=hit_conversations,
        hit_correlations=hit_correlations,
        hit_turns=hit_turns,
    )
    issue_counts = Counter(
        event.issue_type_id or "other.unclassified"
        for event in all_hits
        if event.issue_type_id
    )
    release_counts = Counter(
        str(event.payload.get("releaseId"))
        for event in all_hits
        if event.payload.get("releaseId")
    )
    filtered_hits, hit_records, start_idx, next_cursor = _paginate_hits(
        all_hits,
        issue_type_id=issue_type_id,
        limit=limit,
        cursor=cursor,
        taxonomy=taxonomy,
    )
    recent_hits = [
        {
            "occurredAt": event.occurred_at.isoformat(),
            "conversationId": event.conversation_id,
            "correlationId": event.correlation_id,
            "chunkId": event.payload.get("chunkId"),
            "releaseId": event.payload.get("releaseId"),
            "issueTypeId": event.issue_type_id,
        }
        for event in sorted(all_hits, key=lambda item: item.occurred_at, reverse=True)[:10]
    ]
    return {
        "documentId": document_id,
        "periodDays": period.days,
        "periodPreset": period.preset,
        "startAt": period.start_at.isoformat(),
        "endAt": period.end_at.isoformat(),
        "hitCount": len(all_hits),
        "conversationCount": len(hit_conversations),
        "positiveFeedbackCount": sum(
            1 for event in feedback_events if event.payload.get("rating") == "UP"
        ),
        "negativeFeedbackCount": sum(
            1 for event in feedback_events if event.payload.get("rating") == "DOWN"
        ),
        "issueTypeDistribution": _issue_distribution(issue_counts, taxonomy),
        "releaseAttribution": [
            {"releaseId": release_id, "hitCount": count}
            for release_id, count in release_counts.most_common()
        ],
        "totalHits": len(filtered_hits),
        "hits": hit_records,
        "recentHits": recent_hits,
        "cursor": str(start_idx),
        "nextCursor": next_cursor,
        "hasMore": next_cursor is not None,
        "limit": limit,
        "filterIssueTypeId": issue_type_id,
        "governance": governance,
    }


def build_document_inventory_item(
    document: dict[str, Any],
    governance: dict[str, Any],
    events: list[OperationalEvent],
) -> dict[str, Any]:
    document_id = str(document["document_id"])
    hits = document_hit_events(events, document_id)
    hit_conversations = {event.conversation_id for event in hits if event.conversation_id}
    hit_correlations = {event.correlation_id for event in hits if event.correlation_id}
    hit_turns = {event.turn_id for event in hits if event.turn_id}
    feedback = matching_feedback_events(
        events,
        hit_conversations=hit_conversations,
        hit_correlations=hit_correlations,
        hit_turns=hit_turns,
    )
    issue_counts = Counter(event.issue_type_id or "other.unclassified" for event in hits)
    return {
        "documentId": document_id,
        "title": document.get("title"),
        "summary": document.get("summary"),
        "ownerUnitId": document.get("owner_unit_id"),
        "lifecycleStatus": document.get("status"),
        "formatType": governance.get("formatType", "UNKNOWN"),
        "formatFamily": governance.get(
            "formatFamily",
            normalize_format_type(governance.get("formatType")),
        ),
        "parseStatus": governance.get("parseStatus", "UNKNOWN"),
        "indexStatus": governance.get("indexStatus", "UNKNOWN"),
        "currentPublishedVersionId": document.get("current_published_version_id"),
        "draftVersionId": document.get("draft_version_id"),
        "updatedAt": document.get("updated_at"),
        "portalUrl": governance.get("portalUrl"),
        "hitCount": len(hits),
        "conversationCount": len(hit_conversations),
        "positiveFeedbackCount": sum(
            1 for event in feedback if event.payload.get("rating") == "UP"
        ),
        "negativeFeedbackCount": sum(
            1 for event in feedback if event.payload.get("rating") == "DOWN"
        ),
        "issueTypeDistribution": [
            {"issueTypeId": issue_type_id, "count": count}
            for issue_type_id, count in issue_counts.most_common()
        ],
    }


def paginate_documents(
    documents: list[dict[str, Any]],
    *,
    cursor: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    documents = sorted(documents, key=lambda item: str(item.get("document_id") or ""))
    if cursor:
        documents = [
            document
            for document in documents
            if str(document.get("document_id") or "") > cursor
        ]
    page = documents[:limit]
    next_cursor = None
    if len(documents) > limit and page:
        next_cursor = str(page[-1]["document_id"])
    return documents, page, next_cursor


async def filter_documents_by_format(
    documents: list[dict[str, Any]],
    *,
    format_needle: str | None,
    fetch_governance: Callable[..., Awaitable[dict[str, Any]]],
    indexed_document_ids: set[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]] | None]:
    if not format_needle or format_needle == "UNKNOWN":
        return documents, None
    governance_all = await asyncio.gather(
        *(
            fetch_governance(
                str(document["document_id"]),
                indexed_document_ids=indexed_document_ids,
            )
            for document in documents
        )
    )
    paired = [
        (document, governance)
        for document, governance in zip(documents, governance_all, strict=True)
        if normalize_format_type(governance.get("formatType")) == format_needle
    ]
    return (
        [document for document, _ in paired],
        {str(document["document_id"]): governance for document, governance in paired},
    )
