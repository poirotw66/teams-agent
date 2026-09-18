"""Workbench conversation and broadcast routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI

from operations_core.access import ActorContext
from ai_ops_backoffice.application.workbench.conversations import (
    apply_conversation_action,
    build_conversation_list,
)
from ai_ops_backoffice.application.workbench.conversations import (
    set_emergency_broadcast as set_broadcast,
)

from .context import WorkbenchRouteContext
from .models import BroadcastRequest, ConversationActionRequest


def register_conversation_routes(app: FastAPI, ctx: WorkbenchRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service

    @app.get("/api/console/workbench/conversations")
    async def list_workbench_conversations(
        actor: ActorContext = Depends(current_actor),
    ) -> list[dict[str, Any]]:
        """Return real conversation streams parsed from backend events."""
        require_capability(actor, "ops.conversations.read")
        return await build_conversation_list(
            actor=actor,
            query_service=query_service,
            workbench_state=ctx.get_workbench_state(),
            tickets=ctx.get_all_tickets(),
            normalize_ai_text=ctx.normalize_workbench_ai_text,
        )

    @app.post("/api/console/workbench/conversations/{conversation_id}/action")
    async def handle_conversation_action(
        conversation_id: str,
        payload: ConversationActionRequest,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        """Update conversation resolution or root cause."""
        require_capability(actor, "ops.conversations.read")
        state = ctx.get_workbench_state()
        result = apply_conversation_action(
            conversation_id=conversation_id,
            action=payload.action,
            root_cause=payload.root_cause,
            workbench_state=state,
        )
        ctx.save_workbench_state(state)
        return result

    @app.post("/api/console/workbench/broadcast")
    async def set_emergency_broadcast(
        payload: BroadcastRequest,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        """Set temporary emergency broadcast alert."""
        require_capability(actor, "ops.summary.read")
        state = ctx.get_workbench_state()
        result = set_broadcast(
            message=payload.message,
            duration_hours=payload.durationHours,
            created_by=actor.user_id,
            workbench_state=state,
        )
        ctx.save_workbench_state(state)
        return result
