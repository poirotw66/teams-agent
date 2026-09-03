from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import httpx

from agent_service.operations.access import ActorContext
from agent_service.operations.audit import AuditStore
from agent_service.operations.contracts import (
    DEFAULT_TIMEZONE,
    METRICS_DEFINITION_VERSION,
    OperationalEvent,
    utc_now,
)
from agent_service.operations.runtime import build_ops_runtime
from agent_service.operations.scope import filter_events_by_scope
from agent_service.operations.settings import OpsSettings
from agent_service.operations.taxonomy import TaxonomyRepository
from agent_service.usage import convert_usd_to_twd

from ..settings import BackofficeSettings
from .export_format import wrap_export_payload
from .export_service import ExportJobService
from .periods import ResolvedPeriod, event_in_period, resolve_period
from .usage_projection import (
    UsageDimensions,
    confirmed_zero_call,
    known_cost_total,
    project_usage,
    usage_breakdown,
)


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int((len(ordered) - 1) * ratio)
    return round(ordered[index], 1)


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
    feedback_rating = next(
        (
            str(item.payload.get("rating"))
            for item in related
            if item.event_type == "feedback.recorded" and item.payload.get("rating")
        ),
        None,
    )
    handoff_status = next(
        (
            str(item.payload.get("status") or item.event_type)
            for item in related
            if item.event_type.startswith("handoff.")
        ),
        None,
    )
    resolved_status = next(
        (
            str(item.payload.get("resolvedStatus"))
            for item in related
            if item.event_type == "feedback.recorded" and item.payload.get("resolvedStatus")
        ),
        None,
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
            audit_store_mode=settings.ops_audit_store_mode,
        )
        runtime = build_ops_runtime(ops_settings)
        if runtime is None:
            raise RuntimeError("Operational events are disabled.")
        self._runtime = runtime
        self._environment = ops_settings.environment
        self._metrics = json.loads(settings.ops_metrics_path.read_text(encoding="utf-8"))
        self._event_caches: dict[str, tuple[datetime, list[OperationalEvent]]] = {}
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

    @property
    def environment(self) -> str:
        return self._environment

    def metrics_definitions(self) -> dict[str, Any]:
        return {
            "metricsDefinitionVersion": self._metrics.get(
                "metrics_definition_version",
                METRICS_DEFINITION_VERSION,
            ),
            "pricingVersion": self._metrics.get("pricingVersion", "v1"),
            "timezone": self._metrics.get("timezone", DEFAULT_TIMEZONE),
            "usdTwdExchangeRate": float(self._metrics.get("usdTwdExchangeRate", 31.70)),
            "definitions": self._metrics.get("definitions", {}),
        }

    def _period_bounds(
        self,
        period: ResolvedPeriod | None,
    ) -> tuple[datetime | None, datetime | None]:
        if period is None:
            return None, None
        until = period.end_at if period.explicit_range else None
        return period.start_at, until

    def _cache_key(self, period: ResolvedPeriod | None) -> str:
        since, until = self._period_bounds(period)
        return f"{since.isoformat() if since else ''}|{until.isoformat() if until else ''}"

    async def _events(
        self,
        *,
        period: ResolvedPeriod | None = None,
        force_refresh: bool = False,
    ) -> list[OperationalEvent]:
        cache_ttl = timedelta(seconds=30)
        now = utc_now()
        cache_key = self._cache_key(period)
        cached = self._event_caches.get(cache_key)
        if (
            not force_refresh
            and cached is not None
            and now - cached[0] < cache_ttl
        ):
            return list(cached[1])
        since, until = self._period_bounds(period)
        events: list[OperationalEvent] = []
        cursor: str | None = None
        while True:
            page, cursor = await self._runtime.store.list_events(
                limit=500,
                cursor=cursor,
                since=since,
                until=until,
            )
            events.extend(page)
            if cursor is None:
                break
        self._event_caches[cache_key] = (now, events)
        return events

    def _invalidate_cache(self) -> None:
        self._event_caches.clear()

    def _resolve_period(
        self,
        *,
        preset: str | None = None,
        days: int = 7,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> ResolvedPeriod:
        return resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )

    async def _scoped_events(
        self,
        actor: ActorContext,
        period: ResolvedPeriod,
    ) -> list[OperationalEvent]:
        events = await self._events(period=period)
        in_period = [event for event in events if event_in_period(event.occurred_at, period)]
        return filter_events_by_scope(in_period, actor, self.taxonomy)

    async def purge_expired_events(self) -> dict[str, int]:
        purge = getattr(self._runtime.store, "purge_expired", None)
        if purge is None:
            return {"removed": 0}
        removed = await purge()
        self._invalidate_cache()
        return {"removed": removed}

    async def operations_summary(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 7,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        events = await self._scoped_events(actor, period)
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
                    f"Analytics data is {data_freshness_minutes} minutes old; "
                    "pipeline delay may affect dashboard accuracy."
                )
        return {
            "periodDays": period.days,
            "periodPreset": period.preset,
            "periodStart": period.start_at.isoformat(),
            "periodEnd": period.end_at.isoformat(),
            "timezone": DEFAULT_TIMEZONE,
            "metricsDefinitionVersion": METRICS_DEFINITION_VERSION,
            "metricDefinitions": self._metrics.get("definitions", {}),
            "updatedAt": utc_now().isoformat(),
            "latestEventAt": latest_event_at.isoformat() if latest_event_at else None,
            "dataFreshnessMinutes": data_freshness_minutes,
            "dataDelayWarning": data_delay_warning,
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
            "noAnswerCount": no_answer_count,
            "clarificationCount": clarification_count,
            "handoffCount": len(handoffs),
            "ticketCount": len(tickets),
            "positiveFeedbackCount": sum(
                1 for event in feedback if event.payload.get("rating") == "UP"
            ),
            "negativeFeedbackCount": sum(
                1 for event in feedback if event.payload.get("rating") == "DOWN"
            ),
            "resolvedFeedbackCount": resolved_count,
            "totalTokens": total_tokens,
            "estimatedCostUsd": known_cost_total(usage_events),
            "costCoverage": round(cost_complete / len(usage_events), 4) if usage_events else 0.0,
            "handoffRate": round(len(handoffs) / turn_count, 4),
            "ticketRate": round(len(tickets) / turn_count, 4),
            "errorRate": round(len(failed_requests) / turn_count, 4),
            "p50LatencyMs": _percentile(latencies, 0.5),
            "p95LatencyMs": _percentile(latencies, 0.95),
            "requestFailureCount": len(failed_requests),
        }

    async def list_conversations(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 25,
        cursor: str | None = None,
        actor_ref: str | None = None,
        issue_type_id: str | None = None,
        route: str | None = None,
        conversation_id: str | None = None,
        model: str | None = None,
        has_feedback: bool | None = None,
        handoff: bool | None = None,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        events = await self._scoped_events(actor, period)
        grouped: dict[str, list[OperationalEvent]] = defaultdict(list)
        for event in events:
            if event.conversation_id:
                grouped[event.conversation_id].append(event)
        conversation_ids = sorted(
            grouped,
            key=lambda cid: max(item.occurred_at for item in grouped[cid]),
            reverse=True,
        )
        filtered_ids: list[str] = []
        for cid in conversation_ids:
            if conversation_id and cid != conversation_id:
                continue
            conv_events = grouped[cid]
            if actor_ref and not any(event.actor_ref == actor_ref for event in conv_events):
                continue
            if issue_type_id and not any(
                event.issue_type_id == issue_type_id for event in conv_events
            ):
                continue
            if route and not any(
                event.event_type == "route.selected"
                and str(event.payload.get("route")) == route
                for event in conv_events
            ):
                continue
            if model and not any(
                event.event_type == "usage.recorded"
                and str(event.payload.get("model") or "") == model
                for event in conv_events
            ):
                continue
            has_feedback_event = any(
                event.event_type == "feedback.recorded" for event in conv_events
            )
            if has_feedback is True and not has_feedback_event:
                continue
            if has_feedback is False and has_feedback_event:
                continue
            has_handoff_event = any(
                event.event_type.startswith("handoff.") for event in conv_events
            )
            if handoff is True and not has_handoff_event:
                continue
            if handoff is False and has_handoff_event:
                continue
            filtered_ids.append(cid)
        start = int(cursor or "0")
        page_ids = filtered_ids[start : start + limit]
        items = []
        for conv_id in page_ids:
            conv_events = grouped[conv_id]
            turns = [event for event in conv_events if event.event_type == "turn.received"]
            latest = max(conv_events, key=lambda item: item.occurred_at)
            turn_actor = next((event.actor_ref for event in turns if event.actor_ref), None)
            routes = {
                str(event.payload.get("route"))
                for event in conv_events
                if event.event_type == "route.selected" and event.payload.get("route")
            }
            items.append(
                {
                    "conversationId": conv_id,
                    "turnCount": len(turns),
                    "lastOccurredAt": latest.occurred_at.isoformat(),
                    "actorRef": turn_actor or latest.actor_ref,
                    "channelScope": latest.channel_scope,
                    "routes": sorted(routes),
                }
            )
        next_index = start + len(page_ids)
        return {
            "items": items,
            "nextCursor": str(next_index) if next_index < len(filtered_ids) else None,
            "hasMore": next_index < len(filtered_ids),
        }

    async def conversation_detail(
        self,
        actor: ActorContext,
        conversation_id: str,
        *,
        unmask_reason: str | None = None,
    ) -> dict[str, Any] | None:
        events = filter_events_by_scope(
            [
                event
                for event in await self._events()
                if event.conversation_id == conversation_id
            ],
            actor,
            self.taxonomy,
        )
        if not events:
            return None
        allow_unmasked = (
            actor.has_capability("ops.conversations.unmasked")
            and unmask_reason is not None
            and len(unmask_reason.strip()) >= 3
        )
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
            summary = _summarize_turn_events(event, events)
            turns.append(
                {
                    "turnId": event.turn_id,
                    "occurredAt": event.occurred_at.isoformat(),
                    "correlationId": event.correlation_id,
                    "messageMasked": event.payload.get("messageMasked"),
                    "maskingPolicyVersion": event.payload.get("maskingPolicyVersion"),
                    "masked": not allow_unmasked,
                    **summary,
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
            "unmaskAuthorized": allow_unmasked,
            "turns": turns,
        }

    async def issues_summary(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        all_events = await self._scoped_events(actor, period)
        events = [event for event in all_events if event.event_type == "issue.extracted"]
        correlation_to_issue: dict[str, str] = {}
        for event in all_events:
            if not event.correlation_id or not event.issue_type_id:
                continue
            if event.event_type in {"issue.extracted", "issue.classified"}:
                correlation_to_issue[event.correlation_id] = event.issue_type_id
        issue_feedback_down: Counter[str] = Counter()
        issue_handoffs: Counter[str] = Counter()
        issue_costs: dict[str, float] = defaultdict(float)
        for event in all_events:
            issue_type_id = event.issue_type_id or correlation_to_issue.get(
                event.correlation_id or "", "",
            )
            if not issue_type_id:
                continue
            if event.event_type == "feedback.recorded" and event.payload.get("rating") == "DOWN":
                issue_feedback_down[issue_type_id] += 1
            if event.event_type.startswith("handoff."):
                issue_handoffs[issue_type_id] += 1
        usage_dimensions = UsageDimensions(all_events)
        for event in project_usage(all_events).detail_events:
            _, issue_type_id = usage_dimensions.resolve(event)
            cost = event.payload.get("estimatedCostUsd")
            if issue_type_id != "unknown" and cost is not None:
                issue_costs[issue_type_id] += float(cost)
        counts = Counter(event.issue_type_id or "other.unclassified" for event in events)
        total = sum(counts.values()) or 1
        by_day: dict[str, Counter[str]] = defaultdict(Counter)
        for event in events:
            day = event.occurred_at.date().isoformat()
            by_day[day][event.issue_type_id or "other.unclassified"] += 1
        items = []
        for issue_type_id, count in counts.most_common():
            record = self.taxonomy.get(issue_type_id)
            items.append(
                {
                    "issueTypeId": issue_type_id,
                    "displayName": record.display_name if record else issue_type_id,
                    "parentIssueTypeId": record.parent_issue_type_id if record else None,
                    "count": count,
                    "share": round(count / total, 4),
                    "negativeFeedbackRate": round(issue_feedback_down[issue_type_id] / count, 4),
                    "handoffRate": round(issue_handoffs[issue_type_id] / count, 4),
                    "estimatedCostUsd": round(issue_costs.get(issue_type_id, 0.0), 6),
                }
            )
        return {
            "periodDays": period.days,
            "periodPreset": period.preset,
            "taxonomyVersion": self.taxonomy.version,
            "items": items,
            "hierarchy": _build_issue_hierarchy(items, self.taxonomy),
            "trends": [
                {
                    "date": day,
                    "counts": [
                        {
                            "issueTypeId": issue_type_id,
                            "count": issue_count,
                        }
                        for issue_type_id, issue_count in day_counts.most_common()
                    ],
                }
                for day, day_counts in sorted(by_day.items())
            ],
            "unclassifiedCount": counts.get("other.unclassified", 0),
        }

    async def routes_summary(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        events = await self._scoped_events(actor, period)
        route_events = [
            event
            for event in events
            if event.event_type == "route.selected"
            and (issue_type_id is None or event.issue_type_id == issue_type_id)
        ]
        route_counts = Counter(str(event.payload.get("route") or "UNKNOWN") for event in route_events)
        by_issue: dict[str, Counter[str]] = defaultdict(Counter)
        for event in route_events:
            key = event.issue_type_id or "other.unclassified"
            by_issue[key][str(event.payload.get("route") or "UNKNOWN")] += 1
        issue_items = []
        for issue_id, routes in by_issue.items():
            record = self.taxonomy.get(issue_id)
            issue_items.append(
                {
                    "issueTypeId": issue_id,
                    "displayName": record.display_name if record else issue_id,
                    "routes": [
                        {"route": route, "count": count}
                        for route, count in routes.most_common()
                    ],
                }
            )
        return {
            "periodDays": period.days,
            "periodPreset": period.preset,
            "routeDistribution": [
                {"route": route, "count": count} for route, count in route_counts.most_common()
            ],
            "byIssueType": issue_items,
        }

    async def issue_routes(
        self,
        actor: ActorContext,
        issue_type_id: str,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        summary = await self.routes_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            issue_type_id=issue_type_id,
        )
        record = self.taxonomy.get(issue_type_id)
        issue_item = next(
            (item for item in summary["byIssueType"] if item["issueTypeId"] == issue_type_id),
            None,
        )
        return {
            "issueTypeId": issue_type_id,
            "displayName": record.display_name if record else issue_type_id,
            "periodPreset": summary["periodPreset"],
            "periodDays": summary["periodDays"],
            "routes": issue_item["routes"] if issue_item else [],
        }

    async def costs_summary(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        all_events = await self._scoped_events(actor, period)
        usage_dimensions = UsageDimensions(all_events)
        events = list(project_usage(all_events).detail_events)
        by_day: dict[str, float] = defaultdict(float)
        by_backend: Counter[str] = Counter()
        by_route_cost: dict[str, float] = defaultdict(float)
        by_issue_cost: dict[str, float] = defaultdict(float)
        input_tokens = 0
        output_tokens = 0
        embedding_tokens = 0
        tool_context_tokens = 0
        missing_cost_count = 0
        pricing_versions: Counter[str] = Counter()
        for event in events:
            day = event.occurred_at.date().isoformat()
            cost = event.payload.get("estimatedCostUsd")
            route, issue_type_id = usage_dimensions.resolve(event)
            if cost is None:
                if not confirmed_zero_call(event):
                    missing_cost_count += 1
            else:
                cost_value = float(cost)
                by_day[day] += cost_value
                by_route_cost[route] += cost_value
                by_issue_cost[issue_type_id] += cost_value
            backend = str(event.payload.get("knowledgeBackend") or "unknown")
            by_backend[backend] += 1
            input_tokens += int(event.payload.get("inputTokens") or 0)
            output_tokens += int(event.payload.get("outputTokens") or 0)
            embedding_tokens += int(event.payload.get("embeddingTokens") or 0)
            tool_context_tokens += int(event.payload.get("toolContextTokens") or 0)
            pricing_version = str(event.payload.get("pricingVersion") or "unknown")
            pricing_versions[pricing_version] += 1
        known_total = known_cost_total(events)
        exchange_rate = float(self._metrics.get("usdTwdExchangeRate", 31.70))
        return {
            "periodDays": period.days,
            "periodPreset": period.preset,
            "totalEstimatedCostUsd": known_total,
            "totalEstimatedCostTwd": (
                convert_usd_to_twd(known_total, exchange_rate) if known_total is not None else None
            ),
            "usdTwdExchangeRate": exchange_rate,
            "missingCostEventCount": missing_cost_count,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "embeddingTokens": embedding_tokens,
            "toolContextTokens": tool_context_tokens,
            "llmCallCount": sum(int(event.payload.get("llmCallCount") or 0) for event in events),
            "byDay": [
                {"date": day, "estimatedCostUsd": round(value, 6)}
                for day, value in sorted(by_day.items())
            ],
            "byModel": usage_breakdown(events, "model"),
            "byProvider": usage_breakdown(events, "provider"),
            "byComponent": usage_breakdown(events, "component"),
            "byBackend": [
                {"backend": backend, "eventCount": count}
                for backend, count in by_backend.most_common()
            ],
            "byRoute": [
                {"route": route, "estimatedCostUsd": round(value, 6)}
                for route, value in sorted(
                    by_route_cost.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "byIssueType": [
                {
                    "issueTypeId": issue_type_id,
                    "displayName": (
                        self.taxonomy.get(issue_type_id).display_name
                        if self.taxonomy.get(issue_type_id)
                        else issue_type_id
                    ),
                    "estimatedCostUsd": round(value, 6),
                }
                for issue_type_id, value in sorted(
                    by_issue_cost.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            ],
            "eventCount": len(events),
            "pricingVersion": self._metrics.get("pricingVersion", "v1"),
            "pricingVersionsObserved": [
                {"pricingVersion": version, "eventCount": count}
                for version, count in pricing_versions.most_common()
            ],
        }

    async def _probe_url(self, url: str | None, path: str = "/healthz") -> dict[str, str]:
        if not url:
            return {"status": "UNKNOWN", "note": "URL not configured."}
        target = f"{url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(target)
            if response.status_code < 400:
                return {"status": "READY", "note": f"HTTP {response.status_code}"}
            return {"status": "DEGRADED", "note": f"HTTP {response.status_code}"}
        except httpx.HTTPError as exc:
            return {"status": "DOWN", "note": str(exc)}

    async def _probe_agent_functional(self, url: str | None) -> dict[str, str]:
        if not url:
            return {"status": "UNKNOWN", "note": "Agent API URL not configured."}
        target = f"{url.rstrip('/')}/healthz"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(target)
            if response.status_code >= 400:
                return {"status": "DEGRADED", "note": f"HTTP {response.status_code}"}
            payload = response.json()
            retrieval = str(payload.get("retrieval") or "")
            chunks = int(payload.get("chunks") or 0)
            if retrieval and chunks > 0:
                return {
                    "status": "READY",
                    "note": f"retrieval={retrieval}, chunks={chunks}",
                }
            return {"status": "DEGRADED", "note": "Agent health ok but retrieval index is empty."}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {"status": "DOWN", "note": str(exc)}

    async def _probe_retrieval_search(self, url: str | None) -> dict[str, str]:
        if not url:
            return {"status": "UNKNOWN", "note": "Agent API URL not configured."}
        target = f"{url.rstrip('/')}/retrieval/search"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(
                    target,
                    json={"query": "vpn", "limit": 1, "groups": []},
                )
            if response.status_code == 401:
                return {"status": "READY", "note": "Retrieval endpoint reachable (auth required)."}
            if response.status_code >= 400:
                return {"status": "DEGRADED", "note": f"HTTP {response.status_code}"}
            hits = response.json().get("hits") or []
            return {"status": "READY", "note": f"hits={len(hits)}"}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {"status": "DOWN", "note": str(exc)}

    async def health_summary(self) -> dict[str, Any]:
        agent = await self._probe_url(self._settings.agent_api_url)
        agent_functional = await self._probe_agent_functional(self._settings.agent_api_url)
        retrieval = await self._probe_retrieval_search(self._settings.agent_api_url)
        portal = await self._probe_url(self._settings.knowledge_portal_url)
        adapter = await self._probe_url(self._settings.adapter_api_url)
        ticket = await self._probe_url(self._settings.ticket_service_url, path="/healthz")
        if self._settings.simulate_health_anomalies:
            agent = {"status": "DEGRADED", "note": "Simulated LLM API latency spike."}
            retrieval = {"status": "DOWN", "note": "Simulated RAG index unreachable."}
            ticket = {"status": "DOWN", "note": "Simulated Ticket API timeout."}
        monitoring_links: dict[str, str] = {}
        project_id = self._settings.gcp_project_id
        if project_id:
            monitoring_links["cloudMonitoring"] = (
                f"https://console.cloud.google.com/monitoring/dashboards"
                f"?project={project_id}"
            )
            monitoring_links["cloudLogging"] = (
                f"https://console.cloud.google.com/logs/query;query=resource.type%3D"
                f"%22cloud_run_revision%22%0Aseverity%3E%3DERROR;"
                f"?project={project_id}"
            )
        return {
            "components": [
                {"id": "teams-adapter", **adapter},
                {"id": "agent-service", **agent},
                {"id": "agent-retrieval-index", **agent_functional},
                {"id": "agent-retrieval-search", **retrieval},
                {
                    "id": "analytics-store",
                    "status": "READY",
                    "note": f"mode={self._settings.ops_store_mode}",
                },
                {"id": "knowledge-portal", **portal},
                {"id": "ticket-service", **ticket},
            ],
            "monitoringLinks": monitoring_links,
            "simulatedAnomalies": self._settings.simulate_health_anomalies,
            "updatedAt": utc_now().isoformat(),
        }

    async def list_feedback(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        rating: str | None = None,
        reason: str | None = None,
        resolved_status: str | None = None,
        handoff: bool | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        all_events = await self._scoped_events(actor, period)
        conversation_cache: dict[str, list[OperationalEvent]] = {}
        for event in all_events:
            if not event.conversation_id:
                continue
            conversation_cache.setdefault(event.conversation_id, []).append(event)
        feedback_events = [
            event for event in all_events if event.event_type == "feedback.recorded"
        ]
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
            if (
                event.event_type == "issue.classified"
                and issue_extracted
                and event.issue_occurrence_id == issue_extracted.issue_occurrence_id
            ):
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

    async def document_performance(
        self,
        actor: ActorContext,
        document_id: str,
        *,
        preset: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        period = self._resolve_period(preset=preset, days=days)
        events = await self._scoped_events(actor, period)
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
            "periodDays": period.days,
            "periodPreset": period.preset,
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
            "governance": await self._fetch_document_governance(document_id),
        }

    async def _fetch_document_governance(self, document_id: str) -> dict[str, Any]:
        portal_url = self._settings.knowledge_portal_url.rstrip("/")
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

    async def create_export_job(
        self,
        *,
        actor: ActorContext,
        export_type: str,
        reason: str,
        days: int,
        export_format: str = "json",
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        period_kwargs = {
            "preset": preset,
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
        }
        period = self._resolve_period(**period_kwargs)

        async def runner() -> dict[str, Any]:
            if export_type == "operations_summary":
                data = await self.operations_summary(actor, **period_kwargs)
            elif export_type == "issues_summary":
                data = await self.issues_summary(actor, **period_kwargs)
            elif export_type == "costs_summary":
                data = await self.costs_summary(actor, **period_kwargs)
            elif export_type == "feedback":
                data = await self.list_feedback(actor, **period_kwargs)
            elif export_type == "routes_summary":
                data = await self.routes_summary(actor, **period_kwargs)
            else:
                raise ValueError(f"Unsupported export type: {export_type}")
            return wrap_export_payload(
                data,
                export_type=export_type,
                reason=reason,
                requested_by=actor.user_id,
                requested_role=actor.role,
                export_format=export_format,
                period=period,
                pricing_version=self._metrics.get("pricingVersion"),
            )

        job = await self.export_jobs.create_job(
            actor=actor,
            export_type=export_type,
            reason=reason,
            days=days,
            runner=runner,
            export_format=export_format,
        )
        return {
            "jobId": job.job_id,
            "status": job.status,
            "exportType": job.export_type,
            "exportFormat": job.export_format,
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
            "exportFormat": job.export_format,
            "result": job.result,
            "downloadContent": job.download_content,
            "error": job.error,
            "expiresAt": job.expires_at,
            "completedAt": job.completed_at,
        }

