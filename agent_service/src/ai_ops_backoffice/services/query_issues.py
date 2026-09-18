"""Issue, route, and quality-seed queries for the AI Ops backoffice."""

from __future__ import annotations

from collections import Counter
from typing import Any

from operations_core.access import ActorContext

from .query_helpers import _build_issue_hierarchy
from .query_issues_route_ops import (
    build_route_issue_items,
    collect_issue_route_signals,
    collect_route_attribution,
    filter_route_events,
    index_turn_text,
    issue_lookup_maps,
    serialize_attribution,
    source_events_for_routes,
)
from .query_issues_summary_ops import (
    assemble_issues_summary_payload,
    build_issue_day_trends,
    build_issue_summary_items,
    build_quality_candidate_seed,
    collect_issue_quality_metrics,
    correlation_issue_map,
    filter_issue_summary_items,
    previous_extracted_counts,
    previous_period_for,
)


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

        try:
            prev_events = await self._scoped_events(
                actor,
                previous_period_for(period),
                force_refresh=force_refresh,
            )
            prev_counts, prev_total = previous_extracted_counts(prev_events)
        except Exception:
            prev_counts = Counter()
            prev_total = 0

        correlation_to_issue = correlation_issue_map(all_events)
        (
            feedback_down,
            feedback_up,
            feedback_total,
            handoffs,
            no_answers,
            costs,
        ) = collect_issue_quality_metrics(all_events, correlation_to_issue)

        counts = Counter(event.issue_type_id or "other.unclassified" for event in events)
        items = build_issue_summary_items(
            counts=counts,
            prev_counts=prev_counts,
            prev_total=prev_total,
            taxonomy=self.taxonomy,
            feedback_down=feedback_down,
            feedback_up=feedback_up,
            feedback_total=feedback_total,
            handoffs=handoffs,
            no_answers=no_answers,
            costs=costs,
        )
        categories = sorted({item["ownerUnitId"] for item in items if item.get("ownerUnitId")})
        items, matched_issue_ids = filter_issue_summary_items(
            items,
            taxonomy=self.taxonomy,
            query=query,
            owner_unit_id=owner_unit_id,
        )
        return assemble_issues_summary_payload(
            period=period,
            taxonomy_version=self.taxonomy.version,
            total_count=len(events),
            prev_total=prev_total,
            feedback_down=feedback_down,
            feedback_total=feedback_total,
            handoffs=handoffs,
            no_answers=no_answers,
            categories=categories,
            items=items,
            hierarchy=_build_issue_hierarchy(items, self.taxonomy),
            trends=build_issue_day_trends(events, matched_issue_ids),
            query=query,
            owner_unit_id=owner_unit_id,
            unclassified_count=counts.get("other.unclassified", 0),
        )

    async def quality_candidate_seeds(
        self,
        actor: ActorContext,
        *,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        period = self._resolve_period(days=days)
        events = await self._scoped_events(actor, period)
        correlation_to_issue = {
            event.correlation_id: event.issue_type_id for event in events if event.issue_type_id
        }
        seeds: list[dict[str, Any]] = []
        for event in events:
            issue_type_id = event.issue_type_id or correlation_to_issue.get(event.correlation_id)
            issue_type = self.taxonomy.get(issue_type_id) if issue_type_id else None
            if issue_type is None or not issue_type_id:
                continue
            seed = build_quality_candidate_seed(
                event,
                issue_type_id=issue_type_id,
                issue_type=issue_type,
            )
            if seed is not None:
                seeds.append(seed)
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
        route_events = filter_route_events(
            events,
            issue_type_id=issue_type_id,
            route_filter=route_filter,
        )
        route_counts = Counter(
            str(event.payload.get("route") or "UNKNOWN") for event in route_events
        )
        by_issue, attribution_by_route, attribution_by_issue_route = collect_route_attribution(
            route_events,
            source_events_for_routes(events),
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
            "byIssueType": build_route_issue_items(
                by_issue,
                attribution_by_issue_route,
                self.taxonomy,
            ),
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
        turn_messages, turn_answers = index_turn_text(all_events)
        correlation_to_issue, turn_to_issue = issue_lookup_maps(all_events)
        (
            negative_feedbacks,
            handoff_count,
            no_answer_count,
            issue_event_count,
        ) = collect_issue_route_signals(
            all_events,
            issue_type_id=issue_type_id,
            turn_messages=turn_messages,
            turn_answers=turn_answers,
            correlation_to_issue=correlation_to_issue,
            turn_to_issue=turn_to_issue,
        )
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
