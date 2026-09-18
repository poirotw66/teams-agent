"""Routing node and action handlers for the handoff workflow subgraph."""

from __future__ import annotations

from .confirmation import TicketIntent
from .handoff import ActorType, HandoffCase, HandoffStatus
from .handoff_flow import (
    CANCELLED_MESSAGE,
    DEMO_CLOSED_MESSAGE,
    DEMO_MESSAGE_SAVED,
    DEMO_STARTED_MESSAGE,
    SUMMARY_SUPPLEMENT_MESSAGE,
    HandoffAction,
    authorize_handoff_action,
    is_protocol_close_command,
    offer_message_from_summary_text,
)
from .workflow_handoff_case_ops import HandoffCaseOps
from .workflow_handoff_common import _REVIEW_STATUSES
from .workflow_handoff_ticket_ops import HandoffTicketOps
from .workflow_helpers import AgentState


class HandoffRouteOps(HandoffCaseOps, HandoffTicketOps):
    """Decide and apply the next handoff action for the active case."""

    async def _route_handoff(self, state: AgentState) -> dict:
        ticket_intent = await self._resolve_ticket_intent(state)
        if ticket_intent is TicketIntent.CREATE:
            replay = await self._replay_deduped_ticket(state)
            if replay is not None:
                return replay
        if hasattr(self, "_handoff_enabled") and not self._handoff_enabled():
            return {"handoff_handled": False, "ticket_intent": ticket_intent}
        if self.handoff_repository is None:
            return {"handoff_handled": False, "ticket_intent": ticket_intent}
        identity = self._handoff_identity(state)
        if identity is None:
            return {"handoff_handled": False, "ticket_intent": ticket_intent}
        tenant_id, conversation_id, requester_id = identity
        request = state["request"]
        case = await self.handoff_repository.get_active_case(
            tenant_id, conversation_id, requester_id
        )

        closed = await self._route_protocol_close_if_needed(
            case, request.message.text, requester_id, ticket_intent
        )
        if closed is not None:
            return closed

        superseded = await self._route_supersede_if_needed(state, case, ticket_intent)
        if superseded is not None:
            return superseded

        if ticket_intent is TicketIntent.QUERY:
            return {"handoff_handled": False, "ticket_intent": ticket_intent}

        if case is None and self._is_standalone_human_escalation(state):
            demo = await self._start_standalone_human_demo(state)
            demo["ticket_intent"] = ticket_intent
            return demo

        if case is None:
            return {"handoff_handled": False, "ticket_intent": ticket_intent}

        action = await self._decide_authorized_handoff_action(state, case)
        if case.status == HandoffStatus.DEMO_ACTIVE:
            return await self._route_demo_active_action(
                state, case, action, requester_id
            )
        if case.status not in _REVIEW_STATUSES:
            return {"handoff_handled": False, "handoff_case": case}
        return await self._route_review_action(
            state, case, action, requester_id, ticket_intent
        )

    async def _route_protocol_close_if_needed(
        self,
        case: HandoffCase | None,
        message_text: str,
        requester_id: str,
        ticket_intent: TicketIntent,
    ) -> dict | None:
        # Protocol /close must win before supervisor supersede. Otherwise
        # ASSISTANT_META on "/close" tries DEMO_ACTIVE→CANCELLED and crashes.
        if (
            case is None
            or case.status != HandoffStatus.DEMO_ACTIVE
            or not is_protocol_close_command(message_text)
        ):
            return None
        closed = await self.handoff_repository.close_case(
            case.caseId, requester_id, case.version
        )
        await self._append_handoff_event(
            closed,
            "handoff.closed",
            ActorType.USER,
            requester_id,
            {"fromStatus": "DEMO_ACTIVE", "toStatus": "CLOSED"},
        )
        return {
            "handoff_handled": True,
            "handoff_case": closed,
            "final_response": DEMO_CLOSED_MESSAGE,
            "ticket_intent": ticket_intent,
        }

    async def _route_supersede_if_needed(
        self,
        state: AgentState,
        case: HandoffCase | None,
        ticket_intent: TicketIntent,
    ) -> dict | None:
        if case is None or case.status not in {
            HandoffStatus.SUMMARY_REVIEW,
            HandoffStatus.AWAITING_SUPPLEMENT,
            HandoffStatus.DEMO_ACTIVE,
        }:
            return None
        supersede_reason: str | None = None
        if ticket_intent is TicketIntent.QUERY:
            supersede_reason = "ticket_query"
        elif state.get("supervisor_decision") is not None and (
            state["supervisor_decision"].intent == "ASSISTANT_META"
        ):
            supersede_reason = "assistant_scope"
        if supersede_reason is None:
            return None
        cancelled = await self._cancel_active_handoff(state, reason=supersede_reason)
        return {
            "handoff_handled": False,
            "handoff_case": cancelled,
            "ticket_intent": ticket_intent,
        }

    async def _decide_authorized_handoff_action(
        self, state: AgentState, case: HandoffCase
    ) -> HandoffAction:
        request = state["request"]
        action = await self.handoff_router.decide(
            message=request.message.text,
            case_status=case.status.value,
            case_summary=self._summary_text(case.summary),
            conversation_turns=self._handoff_conversation_turns(state["conversation"]),
            execution_context=state.get("execution_context"),
        )
        return authorize_handoff_action(
            case.status.value,
            action,
            message=request.message.text,
        )

    async def _route_demo_active_action(
        self,
        state: AgentState,
        case: HandoffCase,
        action: HandoffAction,
        requester_id: str,
    ) -> dict:
        if action is HandoffAction.CLOSE:
            closed = await self.handoff_repository.close_case(
                case.caseId, requester_id, case.version
            )
            await self._append_handoff_event(
                closed,
                "handoff.closed",
                ActorType.USER,
                requester_id,
                {"fromStatus": "DEMO_ACTIVE", "toStatus": "CLOSED"},
            )
            return {
                "handoff_handled": True,
                "handoff_case": closed,
                "final_response": DEMO_CLOSED_MESSAGE,
            }
        if action is HandoffAction.CREATE_TICKET:
            return await self._complete_handoff_ticket(
                state,
                case=case,
                requester_id=requester_id,
                from_status=HandoffStatus.DEMO_ACTIVE,
                to_status=HandoffStatus.ROUTED_TO_TICKET,
            )
        await self._append_handoff_event(
            case, "handoff.message_saved", ActorType.USER, requester_id
        )
        return {
            "handoff_handled": True,
            "handoff_case": case,
            "final_response": DEMO_MESSAGE_SAVED,
        }

    async def _route_review_action(
        self,
        state: AgentState,
        case: HandoffCase,
        action: HandoffAction,
        requester_id: str,
        ticket_intent: TicketIntent,
    ) -> dict:
        if action is HandoffAction.UNKNOWN:
            # A missing, failed, or illegal semantic action must not cancel an
            # unresolved case or reinterpret the current turn as a new issue.
            return {
                "handoff_handled": True,
                "handoff_case": case,
                "final_response": offer_message_from_summary_text(
                    self._summary_text(case.summary)
                ),
            }
        if action in {HandoffAction.CANCEL, HandoffAction.CLOSE}:
            return await self._cancel_review_handoff(case, requester_id)
        if action is HandoffAction.REQUEST_SUPPLEMENT:
            return await self._request_review_supplement(case, requester_id)
        if action is HandoffAction.CONTACT_HUMAN:
            active = await self._promote_case_to_demo(case, requester_id)
            return {
                "handoff_handled": True,
                "handoff_case": active,
                "final_response": DEMO_STARTED_MESSAGE,
            }
        if action is HandoffAction.CREATE_TICKET:
            return await self._complete_handoff_ticket(
                state,
                case=case,
                requester_id=requester_id,
                from_status=case.status,
                to_status=HandoffStatus.ROUTED_TO_TICKET,
            )
        if action is HandoffAction.NEW_ISSUE:
            return await self._supersede_handoff_for_resume(
                state,
                case,
                requester_id=requester_id,
                ticket_intent=ticket_intent,
                resume_reason="NEW_ISSUE",
            )
        if action is HandoffAction.REVISE_ISSUE:
            return await self._supersede_handoff_for_resume(
                state,
                case,
                requester_id=requester_id,
                ticket_intent=ticket_intent,
                resume_reason="REVISED_ISSUE",
            )
        if action is HandoffAction.SUPPLEMENT:
            return await self._apply_handoff_supplement(
                state, case, requester_id=requester_id
            )
        return {"handoff_handled": False, "handoff_case": case}

    async def _cancel_review_handoff(
        self, case: HandoffCase, requester_id: str
    ) -> dict:
        cancelled = await self.handoff_repository.transition(
            case.caseId,
            case.status,
            HandoffStatus.CANCELLED,
            case.version,
        )
        await self._append_handoff_event(
            cancelled, "handoff.cancelled", ActorType.USER, requester_id
        )
        return {
            "handoff_handled": True,
            "handoff_case": cancelled,
            "final_response": CANCELLED_MESSAGE,
        }

    async def _request_review_supplement(
        self, case: HandoffCase, requester_id: str
    ) -> dict:
        if case.status is HandoffStatus.SUMMARY_REVIEW:
            case = await self.handoff_repository.transition(
                case.caseId,
                HandoffStatus.SUMMARY_REVIEW,
                HandoffStatus.AWAITING_SUPPLEMENT,
                case.version,
            )
            await self._append_handoff_event(
                case,
                "handoff.supplement_requested",
                ActorType.USER,
                requester_id,
                {"fromStatus": "SUMMARY_REVIEW", "toStatus": "AWAITING_SUPPLEMENT"},
            )
        return {
            "handoff_handled": True,
            "handoff_case": case,
            "final_response": SUMMARY_SUPPLEMENT_MESSAGE,
        }
