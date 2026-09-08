"""Issue, route, and quality-seed queries for the AI Ops backoffice."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from agent_service.operations.access import ActorContext

from .periods import ResolvedPeriod
from .query_helpers import _build_issue_hierarchy
from .usage_projection import UsageDimensions, project_usage


class IssuesQueryMixin:
    """Domain query helpers mixed into BackofficeQueryService."""

    async def issues_summary(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        query: str | None = None,
        owner_unit_id: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        all_events = await self._scoped_events(actor, period, force_refresh=force_refresh)
        events = [event for event in all_events if event.event_type == "issue.extracted"]

        # Resolve previous period for trend comparisons
        duration = period.end_at - period.start_at
        prev_start_at = period.start_at - duration
        prev_end_at = period.start_at
        prev_period = ResolvedPeriod(
            days=period.days,
            preset="custom",
            start_at=prev_start_at,
            end_at=prev_end_at,
            explicit_range=True,
        )
        try:
            prev_events = await self._scoped_events(actor, prev_period, force_refresh=force_refresh)
            prev_extracted = [event for event in prev_events if event.event_type == "issue.extracted"]
            prev_counts = Counter(event.issue_type_id or "other.unclassified" for event in prev_extracted)
            prev_total = len(prev_extracted)
        except Exception:
            prev_counts = Counter()
            prev_total = 0

        correlation_to_issue: dict[str, str] = {}
        for event in all_events:
            if not event.correlation_id or not event.issue_type_id:
                continue
            if event.event_type in {"issue.extracted", "issue.classified"}:
                correlation_to_issue[event.correlation_id] = event.issue_type_id

        issue_feedback_down: Counter[str] = Counter()
        issue_feedback_up: Counter[str] = Counter()
        issue_feedback_total: Counter[str] = Counter()
        issue_handoffs: Counter[str] = Counter()
        issue_no_answers: Counter[str] = Counter()
        issue_costs: dict[str, float] = defaultdict(float)

        for event in all_events:
            issue_type_id = event.issue_type_id or correlation_to_issue.get(
                event.correlation_id or "", "",
            )
            if not issue_type_id:
                continue
            if event.event_type == "feedback.recorded":
                issue_feedback_total[issue_type_id] += 1
                rating = event.payload.get("rating")
                if rating == "DOWN":
                    issue_feedback_down[issue_type_id] += 1
                elif rating == "UP":
                    issue_feedback_up[issue_type_id] += 1
            if event.event_type.startswith("handoff."):
                issue_handoffs[issue_type_id] += 1
            if (
                event.event_type in {"answer.completed", "faq.answered", "knowledge.answered"}
                and event.payload.get("resultType") in {"NO_KNOWLEDGE", "FAILED"}
            ):
                issue_no_answers[issue_type_id] += 1

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
            prev_c = prev_counts.get(issue_type_id, 0)
            change_count = count - prev_c
            if prev_c > 0:
                change_rate = round((count - prev_c) / prev_c, 4)
            elif count > 0 and prev_total > 0:
                change_rate = 1.0
            else:
                change_rate = 0.0

            fb_total = issue_feedback_total[issue_type_id]
            fb_down = issue_feedback_down[issue_type_id]
            fb_up = issue_feedback_up[issue_type_id]
            items.append(
                {
                    "issueTypeId": issue_type_id,
                    "displayName": record.display_name if record else issue_type_id,
                    "parentIssueTypeId": record.parent_issue_type_id if record else None,
                    "ownerUnitId": record.owner_unit_id if record else None,
                    "description": record.description if record else "",
                    "count": count,
                    "previousCount": prev_c,
                    "changeCount": change_count,
                    "changeRate": change_rate,
                    "share": round(count / total, 4),
                    "feedbackCount": fb_total,
                    "positiveFeedbackCount": fb_up,
                    "negativeFeedbackCount": fb_down,
                    "negativeFeedbackRate": round(fb_down / count, 4),
                    "handoffCount": issue_handoffs[issue_type_id],
                    "handoffRate": round(issue_handoffs[issue_type_id] / count, 4),
                    "noAnswerCount": issue_no_answers[issue_type_id],
                    "noAnswerRate": round(issue_no_answers[issue_type_id] / count, 4),
                    "estimatedCostUsd": round(issue_costs.get(issue_type_id, 0.0), 6),
                }
            )

        categories = sorted(
            list(
                {
                    item["ownerUnitId"]
                    for item in items
                    if item.get("ownerUnitId")
                }
            )
        )

        matched_issue_ids: set[str] | None = None
        if query:
            needle = query.casefold()
            items = [
                item
                for item in items
                if needle in item["issueTypeId"].casefold()
                or needle in item["displayName"].casefold()
                or (
                    (rec := self.taxonomy.get(item["issueTypeId"])) is not None
                    and needle in rec.description.casefold()
                )
            ]
            matched_issue_ids = {item["issueTypeId"] for item in items}

        if owner_unit_id:
            if owner_unit_id in {"other.unclassified", "unclassified"}:
                items = [it for it in items if it["issueTypeId"] == "other.unclassified" or not it.get("ownerUnitId")]
            else:
                items = [it for it in items if it.get("ownerUnitId") == owner_unit_id]
            matched_issue_ids = {item["issueTypeId"] for item in items}

        trends = []
        for day, day_counts in sorted(by_day.items()):
            day_items = [
                {"issueTypeId": issue_type_id, "count": issue_count}
                for issue_type_id, issue_count in day_counts.most_common()
                if matched_issue_ids is None or issue_type_id in matched_issue_ids
            ]
            if day_items:
                trends.append({"date": day, "counts": day_items})

        total_count = len(events)
        total_change_count = total_count - prev_total
        total_change_rate = (
            round((total_count - prev_total) / prev_total, 4)
            if prev_total > 0
            else (1.0 if total_count > 0 and prev_total == 0 else 0.0)
        )

        return {
            "periodDays": period.days,
            "periodPreset": period.preset,
            "periodStart": period.start_at.isoformat(),
            "periodEnd": period.end_at.isoformat(),
            "taxonomyVersion": self.taxonomy.version,
            "totalCount": total_count,
            "previousTotalCount": prev_total,
            "totalChangeCount": total_change_count,
            "totalChangeRate": total_change_rate,
            "totalNegativeFeedbackCount": sum(issue_feedback_down.values()),
            "totalFeedbackCount": sum(issue_feedback_total.values()),
            "totalHandoffCount": sum(issue_handoffs.values()),
            "totalNoAnswerCount": sum(issue_no_answers.values()),
            "categories": categories,
            "items": items,
            "hierarchy": _build_issue_hierarchy(items, self.taxonomy),
            "trends": trends,
            "filterQuery": query,
            "filterOwnerUnitId": owner_unit_id,
            "unclassifiedCount": counts.get("other.unclassified", 0),
        }


    async def quality_candidate_seeds(
        self,
        actor: ActorContext,
        *,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        period = self._resolve_period(days=days)
        events = await self._scoped_events(actor, period)
        correlation_to_issue = {
            event.correlation_id: event.issue_type_id
            for event in events
            if event.issue_type_id
        }
        seeds = []
        for event in events:
            issue_type_id = event.issue_type_id or correlation_to_issue.get(event.correlation_id)
            issue_type = self.taxonomy.get(issue_type_id) if issue_type_id else None
            if issue_type is None:
                continue
            case_type = None
            title = None
            description = ""
            if (
                event.event_type in {"answer.completed", "faq.answered", "knowledge.answered"}
                and event.payload.get("resultType") in {"NO_KNOWLEDGE", "FAILED"}
            ):
                case_type = "NO_ANSWER"
                title = f"{issue_type.display_name} 無答案"
                description = str(event.payload.get("answerMasked") or event.payload.get("resultType"))
            elif (
                event.event_type == "issue.classified"
                and event.payload.get("confidenceStatus") == "LOW"
            ):
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
                continue
            seeds.append(
                {
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
                    "document_ids": tuple(
                        value for value in (event.payload.get("documentId"),) if value
                    ),
                    "frequency": 1,
                    "negative_rate": 1 if case_type == "NEGATIVE_FEEDBACK" else 0,
                    "handoff_rate": 1 if case_type == "HANDOFF" else 0,
                    "estimated_cost_impact": 0,
                }
            )
        return seeds


    async def routes_summary(
        self,
        actor: ActorContext,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
        route: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        events = await self._scoped_events(actor, period, force_refresh=force_refresh)
        route_filter = (route or "").strip().upper() or None
        route_events = [
            event
            for event in events
            if event.event_type == "route.selected"
            and (issue_type_id is None or event.issue_type_id == issue_type_id)
            and (
                route_filter is None
                or str(event.payload.get("route") or "UNKNOWN").upper() == route_filter
            )
        ]
        route_counts = Counter(str(event.payload.get("route") or "UNKNOWN") for event in route_events)
        by_issue: dict[str, Counter[str]] = defaultdict(Counter)
        source_events = [
            event
            for event in events
            if event.event_type in {"faq.answered", "knowledge.retrieved", "knowledge.answered"}
        ]
        empty_attribution = {
            "faqIds": Counter(),
            "faqKeys": Counter(),
            "documentIds": Counter(),
            "sourcePaths": Counter(),
            "versionIds": Counter(),
            "releaseIds": Counter(),
        }

        def new_attribution() -> dict[str, Counter[str]]:
            return {key: Counter() for key in empty_attribution}

        attribution_by_route: dict[str, dict[str, Counter[str]]] = defaultdict(new_attribution)
        attribution_by_issue_route: dict[
            tuple[str, str], dict[str, Counter[str]]
        ] = defaultdict(new_attribution)
        for event in route_events:
            key = event.issue_type_id or "other.unclassified"
            selected_route = str(event.payload.get("route") or "UNKNOWN")
            by_issue[key][selected_route] += 1
            matching_sources = [
                source
                for source in source_events
                if (
                    event.issue_occurrence_id
                    and source.issue_occurrence_id == event.issue_occurrence_id
                )
                or (
                    not event.issue_occurrence_id
                    and source.correlation_id == event.correlation_id
                    and source.turn_id == event.turn_id
                    and source.issue_type_id == event.issue_type_id
                )
            ]
            observed: dict[str, set[str]] = defaultdict(set)
            for source in matching_sources:
                payload = source.payload
                if source.event_type == "faq.answered":
                    if payload.get("faqId"):
                        observed["faqIds"].add(str(payload["faqId"]))
                    if payload.get("faqKey"):
                        observed["faqKeys"].add(str(payload["faqKey"]))
                for field, key_name in (
                    ("documentId", "documentIds"),
                    ("sourcePath", "sourcePaths"),
                    ("versionId", "versionIds"),
                    ("releaseId", "releaseIds"),
                ):
                    if payload.get(field):
                        observed[key_name].add(str(payload[field]))
                for citation in payload.get("citations") or []:
                    if not isinstance(citation, dict):
                        continue
                    for field, key_name in (
                        ("documentId", "documentIds"),
                        ("sourcePath", "sourcePaths"),
                        ("versionId", "versionIds"),
                        ("releaseId", "releaseIds"),
                    ):
                        if citation.get(field):
                            observed[key_name].add(str(citation[field]))
            for key_name, values in observed.items():
                attribution_by_route[selected_route][key_name].update(values)
                attribution_by_issue_route[(key, selected_route)][key_name].update(values)

        def serialize_attribution(counters: dict[str, Counter[str]]) -> dict[str, list[dict[str, Any]]]:
            return {
                key_name: [
                    {"id": value, "count": count}
                    for value, count in counter.most_common()
                ]
                for key_name, counter in counters.items()
            }

        issue_items = []
        for issue_id, routes in by_issue.items():
            record = self.taxonomy.get(issue_id)
            issue_items.append(
                {
                    "issueTypeId": issue_id,
                    "displayName": record.display_name if record else issue_id,
                    "routes": [
                        {
                            "route": selected_route,
                            "count": count,
                            "attribution": serialize_attribution(
                                attribution_by_issue_route[(issue_id, selected_route)]
                            ),
                        }
                        for selected_route, count in routes.most_common()
                    ],
                }
            )
        return {
            "periodDays": period.days,
            "periodPreset": period.preset,
            "filterIssueTypeId": issue_type_id,
            "filterRoute": route_filter,
            "routeDistribution": [
                {
                    "route": selected_route,
                    "count": count,
                    "attribution": serialize_attribution(attribution_by_route[selected_route]),
                }
                for selected_route, count in route_counts.most_common()
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
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        all_events = await self._scoped_events(actor, period)
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

        turn_messages: dict[str, str] = {}
        turn_answers: dict[str, str] = {}
        for event in all_events:
            tid = event.turn_id or event.correlation_id or ""
            if not tid:
                continue
            payload = event.payload or {}
            if event.event_type == "turn.received":
                msg = payload.get("messageMasked") or payload.get("userMessage") or payload.get("text")
                if msg:
                    if event.turn_id:
                        turn_messages[event.turn_id] = str(msg)
                    if event.correlation_id:
                        turn_messages[event.correlation_id] = str(msg)
            elif event.event_type in {"answer.completed", "knowledge.answered", "faq.answered"}:
                ans = payload.get("answerMasked") or payload.get("aiReply") or payload.get("text")
                if ans:
                    if event.turn_id:
                        turn_answers[event.turn_id] = str(ans)
                    if event.correlation_id:
                        turn_answers[event.correlation_id] = str(ans)


        correlation_to_issue: dict[str, str] = {}
        turn_to_issue: dict[str, str] = {}
        for event in all_events:
            if not event.issue_type_id:
                continue
            if event.correlation_id:
                correlation_to_issue[event.correlation_id] = event.issue_type_id
            if event.turn_id:
                turn_to_issue[event.turn_id] = event.issue_type_id

        negative_feedbacks: list[dict[str, Any]] = []
        handoff_count = 0
        no_answer_count = 0
        issue_event_count = 0

        for event in all_events:
            ev_issue = (
                event.issue_type_id
                or turn_to_issue.get(event.turn_id or "")
                or correlation_to_issue.get(event.correlation_id or "")
            )
            if ev_issue != issue_type_id:
                continue
            if event.event_type == "issue.extracted":
                issue_event_count += 1
            if event.event_type.startswith("handoff."):
                handoff_count += 1
            if (
                event.event_type in {"answer.completed", "faq.answered", "knowledge.answered"}
                and event.payload.get("resultType") in {"NO_KNOWLEDGE", "FAILED"}
            ):
                no_answer_count += 1
            if event.event_type == "feedback.recorded" and event.payload.get("rating") == "DOWN":
                tid = event.turn_id or event.correlation_id or ""
                payload = event.payload or {}
                negative_feedbacks.append({
                    "eventId": event.event_id,
                    "occurredAt": event.occurred_at.isoformat(),
                    "conversationId": event.conversation_id,
                    "turnId": event.turn_id,
                    "reason": str(payload.get("reason") or "未填寫原因"),
                    "resolvedStatus": payload.get("resolvedStatus"),
                    "userMessage": turn_messages.get(event.turn_id or "") or turn_messages.get(event.correlation_id or "") or "",
                    "aiReply": turn_answers.get(event.turn_id or "") or turn_answers.get(event.correlation_id or "") or "",

                })

        negative_feedbacks.sort(key=lambda x: x["occurredAt"], reverse=True)

        return {
            "issueTypeId": issue_type_id,
            "displayName": record.display_name if record else issue_type_id,
            "description": record.description if record else "",
            "ownerUnitId": record.owner_unit_id if record else None,
            "periodPreset": summary["periodPreset"],
            "periodDays": summary["periodDays"],
            "periodStart": period.start_at.isoformat(),
            "periodEnd": period.end_at.isoformat(),
            "totalCount": issue_event_count,
            "routes": issue_item["routes"] if issue_item else [],
            "negativeFeedbackCount": len(negative_feedbacks),
            "negativeFeedbacks": negative_feedbacks[:10],
            "handoffCount": handoff_count,
            "noAnswerCount": no_answer_count,
        }

