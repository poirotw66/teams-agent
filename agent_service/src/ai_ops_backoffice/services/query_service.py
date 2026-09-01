from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_service.operations.access import ActorContext
from agent_service.operations.audit import AuditStore
from agent_service.operations.contracts import (
    DEFAULT_TIMEZONE,
    METRICS_DEFINITION_VERSION,
    OperationalEvent,
    utc_now,
)
from agent_service.operations.runtime import build_ops_runtime
from agent_service.operations.settings import OpsSettings
from agent_service.operations.taxonomy import TaxonomyRepository

from ..settings import BackofficeSettings
from .export_service import ExportJobService


class BackofficeQueryService:
    def __init__(self, settings: BackofficeSettings) -> None:
        self._settings = settings
        ops_settings = replace(
            OpsSettings.from_env(),
            enabled=True,
            store_mode=settings.ops_store_mode,
            store_path=settings.ops_store_path,
            taxonomy_path=settings.ops_taxonomy_path,
            metrics_path=settings.ops_metrics_path,
            classification_rules_path=settings.ops_classification_rules_path,
        )
        runtime = build_ops_runtime(ops_settings)
        if runtime is None:
            raise RuntimeError("Operational events are disabled.")
        self._runtime = runtime
        self._metrics = json.loads(settings.ops_metrics_path.read_text(encoding="utf-8"))
        self.export_jobs = ExportJobService(
            audit_store=self._runtime.audit_store,
            store_path=settings.ops_store_path.parent / "exports",
            environment=ops_settings.environment,
        )

    @property
    def taxonomy(self) -> TaxonomyRepository:
        return self._runtime.taxonomy

    @property
    def audit_store(self) -> AuditStore:
        return self._runtime.audit_store

    async def _events(self) -> list[OperationalEvent]:
        events: list[OperationalEvent] = []
        cursor: str | None = None
        while True:
            page, cursor = await self._runtime.store.list_events(limit=500, cursor=cursor)
            events.extend(page)
            if cursor is None:
                break
        return events

    def _in_period(self, event: OperationalEvent, *, days: int) -> bool:
        cutoff = utc_now() - timedelta(days=days)
        occurred = event.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=UTC)
        return occurred >= cutoff

    async def operations_summary(self, *, days: int = 7) -> dict[str, Any]:
        events = [event for event in await self._events() if self._in_period(event, days=days)]
        turns = [event for event in events if event.event_type == "turn.received"]
        issues = [event for event in events if event.event_type == "issue.extracted"]
        faq_hits = [event for event in events if event.event_type == "faq.answered"]
        knowledge_hits = [event for event in events if event.event_type == "knowledge.answered"]
        usage_events = [event for event in events if event.event_type == "usage.recorded"]
        conversations = {event.conversation_id for event in turns if event.conversation_id}
        actors = {event.actor_ref for event in turns if event.actor_ref}
        issue_types = Counter(
            event.issue_type_id or "other.unclassified"
            for event in issues
            if event.issue_type_id
        )
        total_cost = sum(
            float(event.payload.get("estimatedCostUsd") or 0)
            for event in usage_events
            if event.payload.get("estimatedCostUsd") is not None
        )
        cost_complete = sum(1 for event in usage_events if event.payload.get("costComplete"))
        return {
            "periodDays": days,
            "timezone": DEFAULT_TIMEZONE,
            "metricsDefinitionVersion": METRICS_DEFINITION_VERSION,
            "updatedAt": utc_now().isoformat(),
            "conversationCount": len(conversations),
            "turnCount": len(turns),
            "activeUserCount": len(actors),
            "issueOccurrenceCount": len(issues),
            "topIssueTypes": [
                {"issueTypeId": key, "count": value}
                for key, value in issue_types.most_common(5)
            ],
            "faqAnswerCount": len(faq_hits),
            "knowledgeAnswerCount": len(knowledge_hits),
            "estimatedCostUsd": round(total_cost, 6),
            "costCoverage": round(cost_complete / len(usage_events), 4)
            if usage_events
            else 0.0,
        }

    async def list_conversations(
        self,
        *,
        days: int = 30,
        limit: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        events = [event for event in await self._events() if self._in_period(event, days=days)]
        grouped: dict[str, list[OperationalEvent]] = defaultdict(list)
        for event in events:
            if event.conversation_id:
                grouped[event.conversation_id].append(event)
        conversation_ids = sorted(
            grouped,
            key=lambda cid: max(item.occurred_at for item in grouped[cid]),
            reverse=True,
        )
        start = int(cursor or "0")
        page_ids = conversation_ids[start : start + limit]
        items = []
        for conversation_id in page_ids:
            conv_events = grouped[conversation_id]
            turns = [event for event in conv_events if event.event_type == "turn.received"]
            latest = max(conv_events, key=lambda item: item.occurred_at)
            items.append(
                {
                    "conversationId": conversation_id,
                    "turnCount": len(turns),
                    "lastOccurredAt": latest.occurred_at.isoformat(),
                    "actorRef": latest.actor_ref,
                    "channelScope": latest.channel_scope,
                }
            )
        next_index = start + len(page_ids)
        return {
            "items": items,
            "nextCursor": str(next_index) if next_index < len(conversation_ids) else None,
            "hasMore": next_index < len(conversation_ids),
        }

    async def conversation_detail(self, conversation_id: str) -> dict[str, Any] | None:
        events = [
            event
            for event in await self._events()
            if event.conversation_id == conversation_id
        ]
        if not events:
            return None
        events.sort(key=lambda item: item.occurred_at)
        turns = []
        for event in events:
            if event.event_type != "turn.received":
                continue
            related = [
                item
                for item in events
                if item.turn_id == event.turn_id and item.event_type != "turn.received"
            ]
            turns.append(
                {
                    "turnId": event.turn_id,
                    "occurredAt": event.occurred_at.isoformat(),
                    "messageMasked": event.payload.get("messageMasked"),
                    "events": [
                        {
                            "eventType": item.event_type,
                            "payload": item.payload,
                            "issueTypeId": item.issue_type_id,
                        }
                        for item in related
                    ],
                }
            )
        return {
            "conversationId": conversation_id,
            "turns": turns,
        }

    async def issues_summary(self, *, days: int = 30) -> dict[str, Any]:
        events = [
            event
            for event in await self._events()
            if self._in_period(event, days=days) and event.event_type == "issue.extracted"
        ]
        counts = Counter(event.issue_type_id or "other.unclassified" for event in events)
        total = sum(counts.values()) or 1
        items = []
        for issue_type_id, count in counts.most_common():
            record = self.taxonomy.get(issue_type_id)
            items.append(
                {
                    "issueTypeId": issue_type_id,
                    "displayName": record.display_name if record else issue_type_id,
                    "count": count,
                    "share": round(count / total, 4),
                }
            )
        return {
            "periodDays": days,
            "taxonomyVersion": self.taxonomy.version,
            "items": items,
            "unclassifiedCount": counts.get("other.unclassified", 0),
        }

    async def costs_summary(self, *, days: int = 30) -> dict[str, Any]:
        events = [
            event
            for event in await self._events()
            if self._in_period(event, days=days) and event.event_type == "usage.recorded"
        ]
        by_day: dict[str, float] = defaultdict(float)
        for event in events:
            day = event.occurred_at.date().isoformat()
            by_day[day] += float(event.payload.get("estimatedCostUsd") or 0)
        return {
            "periodDays": days,
            "totalEstimatedCostUsd": round(sum(by_day.values()), 6),
            "byDay": [{"date": day, "estimatedCostUsd": round(value, 6)} for day, value in sorted(by_day.items())],
            "eventCount": len(events),
        }

    async def health_summary(self) -> dict[str, Any]:
        return {
            "components": [
                {"id": "teams-adapter", "status": "UNKNOWN", "note": "Configure monitoring integration."},
                {"id": "agent-service", "status": "READY" if self._settings.agent_api_url else "UNKNOWN"},
                {"id": "analytics-store", "status": "READY", "mode": self._settings.ops_store_mode},
                {"id": "knowledge-portal", "status": "READY", "url": self._settings.knowledge_portal_url},
            ],
            "updatedAt": utc_now().isoformat(),
        }

    async def list_feedback(
        self,
        *,
        days: int = 30,
        rating: str | None = None,
        reason: str | None = None,
        resolved_status: str | None = None,
        handoff: bool | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        feedback_events, conversation_cache = await self._list_feedback_with_cache(days=days)
        if rating:
            feedback_events = [
                event for event in feedback_events if event.payload.get("rating") == rating
            ]
        if reason:
            feedback_events = [
                event
                for event in feedback_events
                if str(event.payload.get("reason") or "").lower() == reason.lower()
            ]
        if resolved_status:
            feedback_events = [
                event
                for event in feedback_events
                if str(event.payload.get("resolvedStatus") or "").lower()
                == resolved_status.lower()
            ]
        feedback_events.sort(key=lambda item: item.occurred_at, reverse=True)
        items = []
        for event in feedback_events:
            trace = self._build_feedback_trace(event, conversation_cache=conversation_cache)
            if handoff is True and not trace.get("handoffOccurred"):
                continue
            if handoff is False and trace.get("handoffOccurred"):
                continue
            items.append(
                {
                    "occurredAt": event.occurred_at.isoformat(),
                    "conversationId": event.conversation_id,
                    "correlationId": event.correlation_id,
                    "rating": event.payload.get("rating"),
                    "reason": event.payload.get("reason"),
                    "resolvedStatus": event.payload.get("resolvedStatus"),
                    "issueId": event.payload.get("issueId"),
                    "trace": trace,
                }
            )
            if len(items) >= limit:
                break
        return {"items": items, "total": len(items)}

    def _build_feedback_trace(
        self,
        feedback_event: OperationalEvent,
        *,
        conversation_cache: dict[str, list[OperationalEvent]],
    ) -> dict[str, Any]:
        conversation_id = feedback_event.conversation_id
        correlation_id = feedback_event.correlation_id
        issue_id = feedback_event.payload.get("issueId")
        if not conversation_id:
            return {
                "issueTypeId": None,
                "issueDescriptionMasked": None,
                "classificationSource": None,
                "faqKey": None,
                "documentIds": [],
                "releaseIds": [],
                "handoffOccurred": False,
                "handoffStatus": None,
            }

        conv_events = conversation_cache.get(conversation_id, [])

        scoped = [
            event
            for event in conv_events
            if correlation_id is None or event.correlation_id == correlation_id
        ]
        if not scoped:
            scoped = conv_events

        issue_extracted = None
        issue_classified = None
        faq_key = None
        document_ids: list[str] = []
        release_ids: list[str] = []
        handoff_status = None
        handoff_occurred = False

        for event in scoped:
            if event.event_type == "issue.extracted":
                payload_issue_id = event.payload.get("issueId")
                if issue_id is None or payload_issue_id == issue_id:
                    issue_extracted = event
            if event.event_type == "issue.classified":
                if issue_extracted and event.issue_occurrence_id == issue_extracted.issue_occurrence_id:
                    issue_classified = event
            if event.event_type == "faq.answered":
                faq_key = event.payload.get("faqKey") or faq_key
            if event.event_type in {"knowledge.retrieved", "knowledge.answered"}:
                document_id = event.payload.get("documentId")
                if document_id and document_id not in document_ids:
                    document_ids.append(str(document_id))
                release_id = event.payload.get("releaseId")
                if release_id and release_id not in release_ids:
                    release_ids.append(str(release_id))
                for citation in event.payload.get("citations") or []:
                    if not isinstance(citation, dict):
                        continue
                    citation_doc = citation.get("documentId")
                    if citation_doc and citation_doc not in document_ids:
                        document_ids.append(str(citation_doc))
            if event.event_type.startswith("handoff."):
                handoff_occurred = True
                handoff_status = event.payload.get("status") or event.event_type

        issue_type_id = None
        classification_source = None
        if issue_classified is not None:
            issue_type_id = issue_classified.issue_type_id
            classification_source = issue_classified.payload.get("classificationSource")
        elif issue_extracted is not None:
            issue_type_id = issue_extracted.issue_type_id

        record = self.taxonomy.get(issue_type_id) if issue_type_id else None
        return {
            "issueTypeId": issue_type_id,
            "issueTypeDisplayName": record.display_name if record else issue_type_id,
            "issueDescriptionMasked": (
                issue_extracted.payload.get("descriptionMasked") if issue_extracted else None
            ),
            "classificationSource": classification_source,
            "faqKey": faq_key,
            "documentIds": document_ids,
            "releaseIds": release_ids,
            "handoffOccurred": handoff_occurred,
            "handoffStatus": handoff_status,
        }

    async def _list_feedback_with_cache(self, *, days: int) -> tuple[list[OperationalEvent], dict[str, list[OperationalEvent]]]:
        all_events = [event for event in await self._events() if self._in_period(event, days=days)]
        conversation_cache: dict[str, list[OperationalEvent]] = {}
        for event in all_events:
            if not event.conversation_id:
                continue
            conversation_cache.setdefault(event.conversation_id, []).append(event)
        feedback_events = [
            event for event in all_events if event.event_type == "feedback.recorded"
        ]
        return feedback_events, conversation_cache

    async def document_performance(
        self,
        document_id: str,
        *,
        days: int = 30,
    ) -> dict[str, Any]:
        events = [event for event in await self._events() if self._in_period(event, days=days)]
        hits = [
            event
            for event in events
            if event.event_type in {"knowledge.retrieved", "knowledge.answered"}
            and (
                event.payload.get("documentId") == document_id
                or any(
                    citation.get("documentId") == document_id
                    for citation in (event.payload.get("citations") or [])
                    if isinstance(citation, dict)
                )
            )
        ]
        hit_conversations = {
            event.conversation_id
            for event in hits
            if event.conversation_id
        }
        feedback_events = [
            event
            for event in events
            if event.event_type == "feedback.recorded"
            and event.conversation_id in hit_conversations
        ]
        issue_counts = Counter(
            event.issue_type_id or "other.unclassified"
            for event in hits
            if event.issue_type_id
        )
        release_counts = Counter(
            str(event.payload.get("releaseId"))
            for event in hits
            if event.payload.get("releaseId")
        )
        up = sum(1 for event in feedback_events if event.payload.get("rating") == "UP")
        down = sum(1 for event in feedback_events if event.payload.get("rating") == "DOWN")
        issue_distribution = []
        for issue_type_id, count in issue_counts.most_common():
            record = self.taxonomy.get(issue_type_id)
            issue_distribution.append(
                {
                    "issueTypeId": issue_type_id,
                    "displayName": record.display_name if record else issue_type_id,
                    "count": count,
                }
            )
        return {
            "documentId": document_id,
            "periodDays": days,
            "hitCount": len(hits),
            "conversationCount": len(hit_conversations),
            "positiveFeedbackCount": up,
            "negativeFeedbackCount": down,
            "issueTypeDistribution": issue_distribution,
            "releaseAttribution": [
                {"releaseId": release_id, "hitCount": count}
                for release_id, count in release_counts.most_common()
            ],
            "recentHits": [
                {
                    "occurredAt": event.occurred_at.isoformat(),
                    "conversationId": event.conversation_id,
                    "correlationId": event.correlation_id,
                    "chunkId": event.payload.get("chunkId"),
                    "releaseId": event.payload.get("releaseId"),
                    "issueTypeId": event.issue_type_id,
                }
                for event in sorted(hits, key=lambda item: item.occurred_at, reverse=True)[:10]
            ],
        }

    async def create_export_job(
        self,
        *,
        actor: ActorContext,
        export_type: str,
        reason: str,
        days: int,
    ) -> dict[str, Any]:
        async def runner() -> dict[str, Any]:
            if export_type == "operations_summary":
                return await self.operations_summary(days=days)
            if export_type == "issues_summary":
                return await self.issues_summary(days=days)
            if export_type == "costs_summary":
                return await self.costs_summary(days=days)
            if export_type == "feedback":
                return await self.list_feedback(days=days)
            raise ValueError(f"Unsupported export type: {export_type}")

        job = await self.export_jobs.create_job(
            actor=actor,
            export_type=export_type,
            reason=reason,
            days=days,
            runner=runner,
        )
        return {
            "jobId": job.job_id,
            "status": job.status,
            "exportType": job.export_type,
            "expiresAt": job.expires_at,
        }

    async def get_export_job(self, job_id: str, *, actor: ActorContext) -> dict[str, Any] | None:
        job = await self.export_jobs.get_job(job_id, actor=actor)
        if job is None:
            return None
        return {
            "jobId": job.job_id,
            "status": job.status,
            "exportType": job.export_type,
            "result": job.result,
            "error": job.error,
            "expiresAt": job.expires_at,
            "completedAt": job.completed_at,
        }
