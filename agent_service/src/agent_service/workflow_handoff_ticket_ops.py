"""Ticket-related operations for the handoff workflow subgraph."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .confirmation import TicketIntent, classify_ticket_intent
from .contracts import Citation, Issue, IssueResult
from .handoff import ActorType, HandoffCase, HandoffStatus
from .response_builder import build_response
from .ticket import (
    TicketService,
    TicketServiceDisabledError,
    TicketServiceError,
    TicketServiceTimeout,
)
from .workflow_handoff_common import _REVIEW_STATUSES, HandoffCommonOps
from .workflow_helpers import AgentState


class HandoffTicketOps(HandoffCommonOps):
    """Resolve ticket intent and complete handoff-driven ticket creation."""

    async def _resolve_ticket_intent(self, state: AgentState) -> TicketIntent:
        preset = state.get("ticket_intent")
        if preset is not None:
            return preset

        request = state["request"]
        text = request.message.text
        deterministic = classify_ticket_intent(text)
        if deterministic in {
            TicketIntent.DELETE_DENIED,
            TicketIntent.CANCEL,
            TicketIntent.QUERY,
            TicketIntent.CREATE,
        }:
            return deterministic

        return TicketIntent.NONE

    async def _replay_deduped_ticket(self, state: AgentState) -> dict | None:
        request = state["request"]
        tenant_id = request.conversation.tenantId
        ticket_id = await self.ticket_request_dedupe.get_ticket_id(
            tenant_id, request.requestId
        )
        if not ticket_id:
            return None
        issue = Issue(
            id=1,
            description="Replayed ticket request",
            isIT=True,
            readiness="READY",
            route="TICKET",
        )
        result = IssueResult(
            issueId=issue.id,
            resultType="TICKET_CREATED",
            ticketId=ticket_id,
            sources=[Citation(title=f"派工單 ({ticket_id})", url=None)],
        )
        built = build_response(
            issues=[issue],
            results=[result],
            too_many_issues=False,
            settings=self.settings,
            offer_ticket_on_no_knowledge=False,
            correlation_id=state["correlation_id"],
        )
        return {
            "handoff_handled": True,
            "issue_results": [result],
            "final_response": built.text,
            "citations": built.citations,
            "images": built.images,
            "feedback_enabled": built.feedback_enabled,
        }

    async def _deduped_ticket_result(
        self,
        *,
        issue: Issue,
        request_id: str,
        tenant_id: str | None,
        correlation_id: str,
        ticket_service: TicketService,
        requester_id: str,
    ) -> IssueResult | None:
        existing = await self.ticket_request_dedupe.get_ticket_id(tenant_id, request_id)
        if not existing:
            return None
        try:
            ticket = await ticket_service.get_ticket(
                existing, requester_id, correlation_id=correlation_id
            )
        except (TicketServiceDisabledError, TicketServiceTimeout, TicketServiceError):
            ticket = None
        if ticket is None:
            ticket_id = existing
            sources = [Citation(title=f"派工單 ({ticket_id})", url=None)]
        else:
            ticket_id = ticket.id
            sources = [
                Citation(title=f"{ticket.title} ({ticket.status})", url=ticket.url)
            ]
        return IssueResult(
            issueId=issue.id,
            resultType="TICKET_CREATED",
            ticketId=ticket_id,
            sources=sources,
        )

    async def _complete_handoff_ticket(
        self,
        state: AgentState,
        *,
        case: HandoffCase,
        requester_id: str,
        from_status: HandoffStatus,
        to_status: HandoffStatus,
    ) -> dict:
        if from_status in _REVIEW_STATUSES:
            confirmed = case.summary.model_copy(
                update={
                    "confirmedAt": datetime.now(timezone.utc),
                    "confirmedBy": requester_id,
                    "version": case.summary.version + 1,
                }
            )
            case = await self.handoff_repository.update_summary(
                case.caseId, confirmed, case.version
            )
        issue = Issue(
            id=1,
            description=case.summary.issue,
            isIT=True,
            readiness="READY",
            route="TICKET",
        )
        request = state["request"]
        result = await self._handle_ticket(
            issue,
            user=state["user"],
            correlation_id=state["correlation_id"],
            lock=asyncio.Lock(),
            ticket_created={"done": False},
            ticket_intent=TicketIntent.CREATE,
            ticket_body=self._summary_text(case.summary),
            handoff_confirmed=True,
            request_id=request.requestId,
            tenant_id=request.conversation.tenantId,
            idempotency_key=state.get("execution_context").idempotency_key
            if state.get("execution_context")
            else None,
            execution_context=state.get("execution_context"),
        )
        if result.resultType == "TICKET_CREATED":
            routed = await self.handoff_repository.transition(
                case.caseId,
                from_status,
                to_status,
                case.version,
            )
            await self._append_handoff_event(
                routed,
                "handoff.ticket_selected",
                ActorType.USER,
                requester_id,
                {"ticketId": result.ticketId},
            )
            answer = f"已依確認的案件摘要建立派工單：{result.ticketId}"
            return {
                "handoff_handled": True,
                "handoff_case": routed,
                "issue_results": [result],
                "final_response": answer,
            }
        if result.resultType == "NEED_MORE_INFO":
            return {
                "handoff_handled": True,
                "handoff_case": case,
                "issue_results": [result],
                "final_response": result.questions[0],
            }
        return {
            "handoff_handled": True,
            "handoff_case": case,
            "issue_results": [result],
            "final_response": "派工單建立失敗。你仍可回覆「聯絡線上客服」或「取消」。",
        }
