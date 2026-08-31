from __future__ import annotations

from typing import Literal

from ..models import DashboardSummary, PortalActor, WorkQueueItem
from .context import PortalServiceContext


class DashboardService:
    def __init__(self, ctx: PortalServiceContext) -> None:
        self._ctx = ctx

    async def dashboard(self, actor: PortalActor) -> DashboardSummary:
        summary = await self._ctx.repository.dashboard_summary(actor)
        profile: Literal["DEMO", "GOVERNED"] = (
            "DEMO" if self._ctx.settings.demo_mode else "GOVERNED"
        )
        relaxed = self._ctx.settings.effective_relaxed_workflow()
        work_queues = self._work_queues_for_role(actor, summary)
        return summary.model_copy(
            update={
                "relaxed_workflow": relaxed,
                "min_test_cases_for_review": 0 if relaxed else 3,
                "demo_mode": self._ctx.settings.demo_mode,
                "portal_profile": profile,
                "actor_role": actor.role,
                "home_route": self._home_route_for_role(actor),
                "work_queues": work_queues,
                "visible_nav": self._visible_nav_for_role(actor),
            }
        )

    def _work_queues_for_role(
        self, actor: PortalActor, summary: DashboardSummary
    ) -> list[WorkQueueItem]:
        contributor_queues = [
            WorkQueueItem(
                label="我的草稿",
                count=summary.my_drafts,
                route="#/knowledge",
                filter_status="DRAFT",
            ),
            WorkQueueItem(
                label="被退回內容",
                count=summary.my_changes_requested,
                route="#/knowledge",
                filter_status="CHANGES_REQUESTED",
            ),
        ]
        reviewer_queues = [
            WorkQueueItem(
                label="待審文件",
                count=summary.pending_review,
                route="#/reviews",
            ),
        ]
        manager_queues = [
            WorkQueueItem(
                label="待審文件",
                count=summary.pending_review,
                route="#/reviews",
            ),
            WorkQueueItem(
                label="發布失敗",
                count=summary.publish_failed,
                route="#/knowledge",
                filter_status="PUBLISH_FAILED",
            ),
            WorkQueueItem(
                label="即將到期",
                count=summary.review_due_soon,
                route="#/knowledge",
                filter_status="PUBLISHED",
            ),
        ]
        if actor.role == "CONTRIBUTOR":
            return contributor_queues
        if actor.role == "REVIEWER":
            return reviewer_queues
        if actor.role == "AUDITOR":
            return [
                WorkQueueItem(
                    label="稽核紀錄",
                    count=0,
                    route="#/audit",
                )
            ]
        return manager_queues

    def _home_route_for_role(self, actor: PortalActor) -> str:
        if actor.role == "REVIEWER":
            return "#/reviews"
        if actor.role == "AUDITOR":
            return "#/audit"
        return "#/work"

    def _visible_nav_for_role(self, actor: PortalActor) -> list[str]:
        nav = ["work", "knowledge"]
        if actor.role in {"REVIEWER", "MANAGER", "PLATFORM"}:
            nav.append("reviews")
        if actor.role in {"AUDITOR", "MANAGER", "PLATFORM"}:
            nav.append("audit")
        if actor.role in {"MANAGER", "PLATFORM"}:
            nav.append("releases")
        return nav
