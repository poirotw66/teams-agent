"""Workflow node implementations for the handoff subgraph."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .confirmation import TicketIntent, classify_ticket_intent
from .contracts import Citation, ConversationContext, Issue, IssueResult
from .handoff import (
    ActiveHandoffCaseExistsError,
    ActorType,
    CaseSummary,
    HandoffCase,
    HandoffEvent,
    HandoffStatus,
)
from .handoff_flow import (
    CANCELLED_MESSAGE,
    DEMO_CLOSED_MESSAGE,
    DEMO_MESSAGE_SAVED,
    DEMO_STARTED_MESSAGE,
    SUMMARY_SUPPLEMENT_MESSAGE,
    HandoffAction,
    deterministic_summary,
    offer_message,
    offer_message_from_summary_text,
)
from .response_builder import build_response
from .ticket import (
    TicketService,
    TicketServiceDisabledError,
    TicketServiceError,
    TicketServiceTimeout,
)
from .workflow_helpers import AgentState

logger = logging.getLogger(__name__)


class HandoffWorkflowMixin:
    """LangGraph nodes owned by the handoff subgraph."""

    async def _append_handoff_event(
        self,
        case: HandoffCase,
        event_type: str,
        actor_type: ActorType,
        actor_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self.handoff_repository is None:
            return
        await self.handoff_repository.append_event(
            HandoffEvent(
                eventId=str(uuid.uuid4()),
                caseId=case.caseId,
                eventType=event_type,
                actorType=actor_type,
                actorId=actor_id,
                occurredAt=datetime.now(timezone.utc),
                payload=payload or {},
                correlationId=case.correlationId,
                retentionExpiresAt=case.retentionExpiresAt,
            )
        )

    @staticmethod
    def _summary_text(summary: CaseSummary) -> str:
        return deterministic_summary(
            current_message=summary.userNeed,
            issue_descriptions=[summary.issue],
            conversation_highlights=summary.conversationHighlights,
            attempted_solutions=summary.attemptedSolutions,
            now=summary.generatedAt,
        ).render()

    async def _create_handoff_offer(
        self, state: AgentState, issue_descriptions: list[str]
    ) -> HandoffCase | None:
        if self.handoff_repository is None:
            return None
        identity = self._handoff_identity(state)
        if identity is None:
            return None
        tenant_id, conversation_id, requester_id = identity
        request = state["request"]
        now = datetime.now(timezone.utc)
        draft = deterministic_summary(
            current_message=request.message.text,
            issue_descriptions=issue_descriptions,
        )
        summary = CaseSummary(
            issue=draft.issue,
            userNeed=draft.user_need,
            conversationHighlights=draft.conversation_highlights,
            attemptedSolutions=draft.attempted_solutions,
            unresolvedReason=draft.unresolved_reason,
            requestedOutcome=draft.requested_outcome,
            generatedAt=draft.generated_at,
        )
        case = HandoffCase(
            caseId=str(uuid.uuid4()),
            sessionId=str(uuid.uuid4()),
            tenantId=tenant_id,
            conversationId=conversation_id,
            requesterId=requester_id,
            requesterName=request.user.displayName,
            status=HandoffStatus.OFFERED,
            summary=summary,
            createdAt=now,
            updatedAt=now,
            sessionExpiresAt=now + timedelta(hours=self.settings.handoff_demo_timeout_hours),
            retentionExpiresAt=now + timedelta(days=self.settings.handoff_retention_days),
            correlationId=state["correlation_id"],
        )
        try:
            case = await self.handoff_repository.create_case(case)
            await self._append_handoff_event(
                case, "handoff.offered", ActorType.SYSTEM, None
            )
            case = await self.handoff_repository.transition(
                case.caseId,
                HandoffStatus.OFFERED,
                HandoffStatus.SUMMARY_REVIEW,
                case.version,
            )
            await self._append_handoff_event(
                case,
                "handoff.summary_reviewed",
                ActorType.SYSTEM,
                None,
                {"fromStatus": "OFFERED", "toStatus": "SUMMARY_REVIEW"},
            )
            return case
        except ActiveHandoffCaseExistsError:
            return await self.handoff_repository.get_active_case(
                tenant_id, conversation_id, requester_id
            )

    async def _resolve_ticket_intent(self, state: AgentState) -> TicketIntent:
        request = state["request"]
        text = request.message.text
        deterministic = classify_ticket_intent(text)
        if deterministic in {
            TicketIntent.DELETE_DENIED,
            TicketIntent.CANCEL,
            TicketIntent.CREATE,
        }:
            return deterministic
        if await self.ticket_query_router.is_ticket_query(
            message=text,
            conversation_turns=self._handoff_conversation_turns(state["conversation"]),
            execution_context=state.get("execution_context"),
        ):
            return TicketIntent.QUERY
        return TicketIntent.NONE

    @staticmethod
    def _handoff_conversation_turns(conversation: ConversationContext) -> list[str]:
        bounded = conversation.messages[-10:]
        return [f"{message.role}: {message.text}" for message in bounded]

    async def _cancel_active_handoff(
        self,
        state: AgentState,
        *,
        reason: str,
    ) -> HandoffCase | None:
        if self.handoff_repository is None:
            return None
        identity = self._handoff_identity(state)
        if identity is None:
            return None
        tenant_id, conversation_id, requester_id = identity
        case = await self.handoff_repository.get_active_case(
            tenant_id, conversation_id, requester_id
        )
        if case is None or case.status not in {
            HandoffStatus.SUMMARY_REVIEW,
            HandoffStatus.DEMO_ACTIVE,
        }:
            return case
        cancelled = await self.handoff_repository.transition(
            case.caseId,
            case.status,
            HandoffStatus.CANCELLED,
            case.version,
        )
        await self._append_handoff_event(
            cancelled,
            "handoff.superseded",
            ActorType.USER,
            requester_id,
            {
                "fromStatus": case.status.value,
                "toStatus": "CANCELLED",
                "reason": reason,
            },
        )
        return cancelled

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
        if from_status is HandoffStatus.SUMMARY_REVIEW:
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

    async def _route_handoff(self, state: AgentState) -> dict:
        replay = await self._replay_deduped_ticket(state)
        if replay is not None:
            return replay
        ticket_intent = await self._resolve_ticket_intent(state)
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

        if case is not None and case.status in {
            HandoffStatus.SUMMARY_REVIEW,
            HandoffStatus.DEMO_ACTIVE,
        }:
            supersede_reason: str | None = None
            if ticket_intent is TicketIntent.QUERY:
                supersede_reason = "ticket_query"
            elif state.get("supervisor_decision") is not None and (
                state["supervisor_decision"].intent == "ASSISTANT_META"
            ):
                supersede_reason = "assistant_scope"
            if supersede_reason is not None:
                cancelled = await self._cancel_active_handoff(
                    state, reason=supersede_reason
                )
                return {
                    "handoff_handled": False,
                    "handoff_case": cancelled,
                    "ticket_intent": ticket_intent,
                }

        if ticket_intent is TicketIntent.QUERY:
            return {"handoff_handled": False, "ticket_intent": ticket_intent}

        if case is None:
            return {"handoff_handled": False, "ticket_intent": ticket_intent}

        action = await self.handoff_router.decide(
            message=request.message.text,
            case_status=case.status.value,
            case_summary=self._summary_text(case.summary),
            conversation_turns=self._handoff_conversation_turns(state["conversation"]),
            execution_context=state.get("execution_context"),
        )

        if case.status == HandoffStatus.DEMO_ACTIVE:
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

        if case.status != HandoffStatus.SUMMARY_REVIEW:
            return {"handoff_handled": False, "handoff_case": case}

        if action is HandoffAction.UNKNOWN:
            # A missing or failed semantic model must not cancel an unresolved
            # case or reinterpret the current turn as a new issue. Keep the
            # case in review and render its available next actions again.
            return {
                "handoff_handled": True,
                "handoff_case": case,
                "final_response": offer_message_from_summary_text(
                    self._summary_text(case.summary)
                ),
            }

        if action in {HandoffAction.CANCEL, HandoffAction.CLOSE}:
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
        if action is HandoffAction.REQUEST_SUPPLEMENT:
            return {
                "handoff_handled": True,
                "handoff_case": case,
                "final_response": SUMMARY_SUPPLEMENT_MESSAGE,
            }
        if action is HandoffAction.CONTACT_HUMAN:
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
            active = await self.handoff_repository.transition(
                case.caseId,
                HandoffStatus.SUMMARY_REVIEW,
                HandoffStatus.DEMO_ACTIVE,
                case.version,
            )
            await self._append_handoff_event(
                active,
                "handoff.accepted",
                ActorType.USER,
                requester_id,
                {"fromStatus": "SUMMARY_REVIEW", "toStatus": "DEMO_ACTIVE"},
            )
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
                from_status=HandoffStatus.SUMMARY_REVIEW,
                to_status=HandoffStatus.ROUTED_TO_TICKET,
            )

        if action is not HandoffAction.SUPPLEMENT:
            cancelled = await self.handoff_repository.transition(
                case.caseId,
                HandoffStatus.SUMMARY_REVIEW,
                HandoffStatus.CANCELLED,
                case.version,
            )
            await self._append_handoff_event(
                cancelled,
                "handoff.superseded",
                ActorType.USER,
                requester_id,
                {
                    "fromStatus": "SUMMARY_REVIEW",
                    "toStatus": "CANCELLED",
                    "reason": action.value.lower(),
                },
            )
            return {
                "handoff_handled": False,
                "handoff_case": cancelled,
                "handoff_superseded_new_issue": action is HandoffAction.NEW_ISSUE,
                "ticket_intent": ticket_intent,
            }

        draft = deterministic_summary(
            current_message=request.message.text,
            issue_descriptions=[case.summary.issue],
            conversation_highlights=[
                *case.summary.conversationHighlights,
                request.message.text,
            ],
            attempted_solutions=case.summary.attemptedSolutions,
        )
        updated_summary = CaseSummary(
            issue=draft.issue,
            userNeed=draft.user_need,
            conversationHighlights=draft.conversation_highlights,
            attemptedSolutions=draft.attempted_solutions,
            unresolvedReason=draft.unresolved_reason,
            requestedOutcome=draft.requested_outcome,
            generatedAt=draft.generated_at,
            version=case.summary.version + 1,
        )
        case = await self.handoff_repository.update_summary(
            case.caseId, updated_summary, case.version
        )
        await self._append_handoff_event(
            case,
            "handoff.summary_supplemented",
            ActorType.USER,
            requester_id,
        )
        return {
            "handoff_handled": True,
            "handoff_case": case,
            "final_response": offer_message(draft),
        }

    async def _evaluate_handoff(self, state: AgentState) -> dict:
        if self.handoff_repository is None:
            return {"handoff_handled": False}
        if state.get("handoff_superseded_new_issue"):
            return {"handoff_handled": False}
        issue_results = state.get("issue_results", [])
        if any(
            result.resultType in {"KNOWLEDGE_ANSWERED", "FAQ_ANSWERED"}
            for result in issue_results
        ):
            await self._cancel_active_handoff(state, reason="knowledge_answered")
            return {"handoff_handled": False}
        trigger_results = {
            result.issueId
            for result in state.get("issue_results", [])
            if result.resultType in {"NO_KNOWLEDGE", "FAILED"}
        }
        if not trigger_results:
            return {"handoff_handled": False}
        descriptions = [
            issue.description
            for issue in state.get("issues", [])
            if issue.id in trigger_results
        ]
        case = await self._create_handoff_offer(state, descriptions)
        if case is None:
            return {"handoff_handled": False}
        draft = deterministic_summary(
            current_message=case.summary.userNeed,
            issue_descriptions=[case.summary.issue],
            conversation_highlights=case.summary.conversationHighlights,
            attempted_solutions=case.summary.attemptedSolutions,
        )
        return {
            "handoff_handled": True,
            "handoff_case": case,
            "final_response": offer_message(draft),
            "citations": [],
            "images": [],
            "feedback_enabled": False,
        }

    def _handoff_identity(self, state: AgentState) -> tuple[str, str, str] | None:
        request = state["request"]
        tenant_id = request.conversation.tenantId
        conversation_id = request.conversation.conversationId
        requester_id = request.user.entraObjectId or request.user.teamsUserId
        if not tenant_id or not conversation_id or not requester_id:
            return None
        return tenant_id, conversation_id, requester_id
