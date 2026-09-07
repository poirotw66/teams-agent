"""Domain query mixin: KnowledgeQueryMixin."""

from __future__ import annotations

from typing import Any

from agent_service.operations.access import ActorContext
from collections import Counter
from agent_service.operations.contracts import OperationalEvent
from .query_helpers import _is_published_knowledge_hit
import asyncio
import httpx

class KnowledgeQueryMixin:
    async def document_performance(
        self,
        actor: ActorContext,
        document_id: str,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        events = await self._scoped_events(actor, period, force_refresh=force_refresh)
        all_hits = [
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
        hit_conversations = {event.conversation_id for event in all_hits if event.conversation_id}
        hit_correlations = {event.correlation_id for event in all_hits if event.correlation_id}
        hit_turns = {event.turn_id for event in all_hits if event.turn_id}

        feedback_events = [
            event
            for event in events
            if event.event_type == "feedback.recorded"
            and (
                (event.correlation_id and event.correlation_id in hit_correlations)
                or (event.turn_id and event.turn_id in hit_turns)
                or (not event.correlation_id and not event.turn_id and event.conversation_id in hit_conversations)
            )
        ]
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
        up = sum(1 for event in feedback_events if event.payload.get("rating") == "UP")
        down = sum(1 for event in feedback_events if event.payload.get("rating") == "DOWN")
        issue_distribution = []
        for itype_id, count in issue_counts.most_common():
            record = self.taxonomy.get(itype_id)
            issue_distribution.append(
                {
                    "issueTypeId": itype_id,
                    "displayName": record.display_name if record else itype_id,
                    "count": count,
                }
            )

        filtered_hits = (
            [h for h in all_hits if h.issue_type_id == issue_type_id]
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

        hit_records = [
            {
                "occurredAt": event.occurred_at.isoformat(),
                "conversationId": event.conversation_id,
                "correlationId": event.correlation_id,
                "turnId": event.turn_id,
                "chunkId": event.payload.get("chunkId"),
                "releaseId": event.payload.get("releaseId"),
                "issueTypeId": event.issue_type_id,
                "issueTypeDisplayName": (
                    self.taxonomy.get(event.issue_type_id).display_name
                    if event.issue_type_id and self.taxonomy.get(event.issue_type_id)
                    else event.issue_type_id
                ),
            }
            for event in page_hits
        ]

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
            "positiveFeedbackCount": up,
            "negativeFeedbackCount": down,
            "issueTypeDistribution": issue_distribution,
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
            "governance": await self._fetch_document_governance(document_id),
        }


    async def list_documents(
        self,
        actor: ActorContext,
        *,
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
        preset: str | None = None,
        days: int = 30,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        period = self._resolve_period(preset=preset, days=days)
        events = await self._scoped_events(actor, period)
        inventory = await self._fetch_document_inventory(
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
        )
        documents = [
            document
            for document in inventory["items"]
            if actor.allows_owner_unit(document.get("owner_unit_id"))
        ]
        documents.sort(key=lambda item: str(item.get("document_id") or ""))
        total = len(documents)
        if cursor:
            documents = [
                document
                for document in documents
                if str(document.get("document_id") or "") > cursor
            ]
        page = documents[:limit]
        governance = await asyncio.gather(
            *(
                self._fetch_document_governance(str(document["document_id"]))
                for document in page
            )
        )
        items = [
            self._document_inventory_item(document, governance_item, events)
            for document, governance_item in zip(page, governance, strict=True)
        ]
        next_cursor = None
        if len(documents) > limit and page:
            next_cursor = str(page[-1]["document_id"])
        return {
            "items": items,
            "total": total,
            "nextCursor": next_cursor,
            "periodDays": period.days,
            "periodPreset": period.preset,
            "portalStatus": inventory["status"],
            "warning": inventory.get("warning"),
        }


    def _document_inventory_item(
        self,
        document: dict[str, Any],
        governance: dict[str, Any],
        events: list[OperationalEvent],
    ) -> dict[str, Any]:
        document_id = str(document["document_id"])
        hits = [
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
        hit_conversations = {event.conversation_id for event in hits if event.conversation_id}
        hit_correlations = {event.correlation_id for event in hits if event.correlation_id}
        hit_turns = {event.turn_id for event in hits if event.turn_id}
        feedback = [
            event
            for event in events
            if event.event_type == "feedback.recorded"
            and (
                (event.correlation_id and event.correlation_id in hit_correlations)
                or (event.turn_id and event.turn_id in hit_turns)
                or (not event.correlation_id and not event.turn_id and event.conversation_id in hit_conversations)
            )
        ]
        issue_counts = Counter(
            event.issue_type_id or "other.unclassified"
            for event in hits
        )
        return {
            "documentId": document_id,
            "title": document.get("title"),
            "summary": document.get("summary"),
            "ownerUnitId": document.get("owner_unit_id"),
            "lifecycleStatus": document.get("status"),
            "formatType": governance.get("formatType", "UNKNOWN"),
            "parseStatus": governance.get("parseStatus", "UNKNOWN"),
            "indexStatus": governance.get("indexStatus", document.get("status")),
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


    async def _fetch_document_inventory(
        self,
        *,
        status: str | None,
        owner_unit_id: str | None,
        query: str | None,
    ) -> dict[str, Any]:
        portal_url = (
            self._settings.knowledge_internal_url or self._settings.knowledge_portal_url
        ).rstrip("/")
        headers = {
            "X-Portal-User-Id": "ai-ops-backoffice",
            "X-Portal-User-Name": "AI%20Ops%20Backoffice",
            "X-Portal-Role": "PLATFORM",
            "X-Portal-Owner-Units": self._settings.default_owner_unit_id,
        }
        params = {
            key: value
            for key, value in {
                "status": status,
                "owner_unit_id": owner_unit_id,
                "query": query,
            }.items()
            if value
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"{portal_url}/api/documents",
                    headers=headers,
                    params=params,
                )
            if response.status_code >= 400:
                return {
                    "status": "unavailable",
                    "items": [],
                    "warning": f"Portal returned HTTP {response.status_code}",
                }
            payload = response.json()
            items = payload.get("items") or []
            return {
                "status": "available",
                "items": [item for item in items if isinstance(item, dict)],
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {"status": "unavailable", "items": [], "warning": str(exc)}


    async def _fetch_document_governance(self, document_id: str) -> dict[str, Any]:
        portal_url = (
            self._settings.knowledge_internal_url or self._settings.knowledge_portal_url
        ).rstrip("/")
        headers = {
            "X-Portal-User-Id": "ai-ops-backoffice",
            "X-Portal-User-Name": "AI%20Ops%20Backoffice",
            "X-Portal-Role": "PLATFORM",
            "X-Portal-Owner-Units": self._settings.default_owner_unit_id,
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"{portal_url}/api/documents/{document_id}",
                    headers=headers,
                )
            if response.status_code == 404:
                return {"status": "not_found", "portalUrl": portal_url}
            if response.status_code >= 400:
                return {
                    "status": "unavailable",
                    "portalUrl": portal_url,
                    "note": f"Portal returned HTTP {response.status_code}",
                }
            payload = response.json()
            document = payload.get("document") or {}
            published = payload.get("published_version") or {}
            draft = payload.get("draft_version") or {}
            raw_format = published.get("source_type") or draft.get("source_type") or "UNKNOWN"
            format_type = "PDF" if raw_format == "PDF" else raw_format
            return {
                "status": "available",
                "portalUrl": f"{portal_url}/#document/{document_id}",
                "lifecycleStatus": document.get("status"),
                "formatType": format_type,
                "parseStatus": (
                    "READY"
                    if (published.get("parse_preview") or draft.get("parse_preview"))
                    else "NOT_PARSED"
                ),
                "indexStatus": document.get("status"),
                "currentPublishedVersionId": document.get("current_published_version_id"),
                "draftVersionId": document.get("draft_version_id"),
                "statusLabel": payload.get("status_label") or document.get("status"),
            }
        except httpx.HTTPError as exc:
            return {
                "status": "unavailable",
                "portalUrl": portal_url,
                "note": str(exc),
            }

