"""Knowledge-gap summary scoring routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query

from .context import QualityRouteContext


def register_gap_routes(app: FastAPI, ctx: QualityRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service

    @app.get("/api/gaps/summary")
    async def gap_summary(
        preset: str | None = None,
        days: int = Query(default=30, ge=1, le=365),
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.quality.read")
        issues = await query_service.issues_summary(
            actor,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        weights = {
            "frequency": 30.0,
            "noAnswerRate": 20.0,
            "negativeFeedbackRate": 25.0,
            "handoffRate": 15.0,
            "estimatedCostUsd": 10.0,
        }
        items = []
        max_frequency = max((item["count"] for item in issues["items"]), default=1)
        max_cost = max((item["estimatedCostUsd"] for item in issues["items"]), default=1) or 1
        for issue in issues["items"]:
            components = {
                "frequency": round(issue["count"] / max_frequency * weights["frequency"], 4),
                "noAnswerRate": round(issue["noAnswerRate"] * weights["noAnswerRate"], 4),
                "negativeFeedbackRate": round(
                    issue["negativeFeedbackRate"] * weights["negativeFeedbackRate"], 4
                ),
                "handoffRate": round(issue["handoffRate"] * weights["handoffRate"], 4),
                "estimatedCostUsd": round(
                    issue["estimatedCostUsd"] / max_cost * weights["estimatedCostUsd"], 4
                ),
            }
            items.append(
                {**issue, "gapScore": round(sum(components.values()), 4), "components": components}
            )

        if issue_type_id:
            needle = issue_type_id.casefold()
            items = [
                item
                for item in items
                if needle in str(item.get("issueTypeId", "")).casefold()
                or needle in str(item.get("displayName", "")).casefold()
            ]

        reverse = sort_order.lower() != "asc"
        if sort_by == "frequency":
            items.sort(key=lambda item: item["count"], reverse=reverse)
        elif sort_by == "negativeFeedbackRate":
            items.sort(key=lambda item: item["negativeFeedbackRate"], reverse=reverse)
        elif sort_by == "noAnswerRate":
            items.sort(key=lambda item: item["noAnswerRate"], reverse=reverse)
        elif sort_by == "handoffRate":
            items.sort(key=lambda item: item["handoffRate"], reverse=reverse)
        elif sort_by == "cost":
            items.sort(key=lambda item: item["estimatedCostUsd"], reverse=reverse)
        else:
            items.sort(key=lambda item: item["gapScore"], reverse=reverse)
        return {
            "scoreVersion": "gap-score-v1",
            "weights": weights,
            "taxonomyVersion": issues["taxonomyVersion"],
            "items": items,
        }
