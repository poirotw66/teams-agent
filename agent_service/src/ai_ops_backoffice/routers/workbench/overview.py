"""Workbench overview route."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.application.workbench.overview import build_workbench_overview

from .context import WorkbenchRouteContext


def register_overview_routes(app: FastAPI, ctx: WorkbenchRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @app.get("/api/console/workbench/overview")
    async def get_workbench_overview(
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.summary.read")
        return await build_workbench_overview(
            actor=actor,
            list_conversations=ctx.query_service.list_conversations,
            get_all_tickets=ctx.get_all_tickets,
            get_workbench_state=ctx.get_workbench_state,
            data_dir=ctx.data_dir,
        )
