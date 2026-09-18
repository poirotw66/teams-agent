"""Workbench ticket routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI

from agent_service.operations.access import ActorContext

from .context import WorkbenchRouteContext
from .models import TicketCreateRequest
from .persistence import save_json_safe


def register_ticket_routes(app: FastAPI, ctx: WorkbenchRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    tickets_file = ctx.tickets_file

    @app.get("/api/console/workbench/tickets")
    async def list_workbench_tickets(
        actor: ActorContext = Depends(current_actor),
    ) -> list[dict[str, Any]]:
        """Return real IT tickets from tickets.json."""
        require_capability(actor, "ops.conversations.read")
        return ctx.get_all_tickets()

    @app.post("/api/console/workbench/tickets")
    async def create_workbench_ticket(
        payload: TicketCreateRequest,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        """Create and persist a new physical IT repair ticket."""
        require_capability(actor, "ops.conversations.read")

        tickets = ctx.get_all_tickets()
        ticket_count = len(tickets) + 1
        ticket_num = f"IT-2026-{ticket_count:04d}"
        now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

        new_ticket = {
            "id": f"ticket-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            "ticket_number": ticket_num,
            "conversation_id": payload.conversationId,
            "reporter_name": payload.reporterName,
            "reporter_dept": payload.reporterDept,
            "reporter_ext": payload.reporterExt,
            "category": payload.category,
            "title": payload.title,
            "assigned_team": payload.assignedTeam,
            "assigned_agent": "待指派 (工程師)",
            "status": "IN_PROGRESS",
            "resolution_note": f"工程師已接單處理中（{payload.assignedTeam}）",
            "created_at": now_str,
            "updated_at": now_str,
        }

        tickets.insert(0, new_ticket)
        save_json_safe(tickets_file, tickets)

        # Update conversation status and linked ticket in state
        if payload.conversationId:
            state = ctx.get_workbench_state()
            state.setdefault("associated_tickets", {})[payload.conversationId] = ticket_num
            ctx.save_workbench_state(state)

        return new_ticket
