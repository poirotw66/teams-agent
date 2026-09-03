"""Workflow node implementations for the clarification subgraph."""

from __future__ import annotations

import asyncio

from .confirmation import TicketIntent, is_pending_ticket_offer_confirmation
from .contracts import AgentRequest, ConversationContext
from .execution_context import ExecutionContext
from .extractor import HUMAN_ESCALATION_ISSUE_DESCRIPTION, merge_pending_ticket_issues
from .graph import user_context_from_identity
from .supervisor import ConversationSupervisorDecision
from .workflow_helpers import (
    AgentState,
    _complete_complementary_pending_issue,
    _conversation_turns_for_supervisor,
    _has_pending_ticket_offer,
    _is_pending_ticket_detail,
    _issues_for_create_offer,
    _needs_history_for_follow_up,
    _pending_clarifications,
    _pending_context_to_ready_issue,
    _pending_offer_issues,
    _recent_ticket_contexts,
    _requests_ticket_offer,
    assistant_scope_issue,
    greeting_issue_from_message,
    non_it_issue_from_message,
)


class ClarificationWorkflowMixin:
    """LangGraph nodes owned by the clarification subgraph."""

    @staticmethod
    def _ticket_intent_from_supervisor(
        decision: ConversationSupervisorDecision,
    ) -> dict:
        if decision.intent == "TICKET_QUERY" or decision.requestedAction == "QUERY_TICKETS":
            return {"ticket_intent": TicketIntent.QUERY}
        if decision.intent == "TICKET_CREATE" or decision.requestedAction == "CREATE_TICKET":
            return {"ticket_intent": TicketIntent.CREATE}
        return {}

    @classmethod
    def _apply_supervisor_routing(
        cls,
        conversation: ConversationContext,
        request: AgentRequest,
        decision: ConversationSupervisorDecision,
    ) -> dict:
        """Apply the supervisor LLM decision to LangGraph routing state."""
        routing = cls._ticket_intent_from_supervisor(decision)
        if _pending_clarifications(conversation) or _has_pending_ticket_offer(conversation):
            return routing

        if decision.intent == "NON_IT":
            return {
                **routing,
                "skip_issue_pipeline": True,
                "issues": [non_it_issue_from_message(request.message.text)],
                "it_issues": [],
                "issue_results": [],
            }
        if decision.intent == "GREETING":
            return {
                **routing,
                "skip_issue_pipeline": True,
                "issues": [greeting_issue_from_message(request.message.text)],
                "it_issues": [],
                "issue_results": [],
            }
        if decision.intent == "ASSISTANT_META":
            return {
                **routing,
                "skip_issue_pipeline": True,
                "issues": [assistant_scope_issue()],
                "it_issues": [],
                "issue_results": [],
            }
        return routing

    async def _load_conversation(self, state: AgentState) -> dict:
        request = state["request"]
        user = user_context_from_identity(request.user)
        teams_conversation_id = (
            request.conversation.conversationId or f"req:{request.requestId}"
        )
        teams_user_id = (
            request.user.teamsUserId or request.user.entraObjectId or "anonymous"
        )
        conversation = await self.conversation_service.load_or_create(
            tenant_id=request.conversation.tenantId,
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
        )
        knowledge_backend = None
        if hasattr(self.knowledge_service, "resolve_backend"):
            knowledge_backend = await self.knowledge_service.resolve_backend(request)
        execution_context = ExecutionContext.from_request(
            settings=self.settings,
            correlation_id=state["correlation_id"],
            request_id=request.requestId,
            tenant_id=request.conversation.tenantId,
            team_id=request.conversation.teamId,
            knowledge_backend=knowledge_backend,
        )
        supervisor_decision = await self.supervisor.decide(
            message=request.message.text,
            pending_clarification=bool(
                _pending_clarifications(conversation)
                or _has_pending_ticket_offer(conversation)
            ),
            recent_turns=_conversation_turns_for_supervisor(conversation) or None,
            execution_context=execution_context,
        )
        routing = self._apply_supervisor_routing(
            conversation, request, supervisor_decision
        )
        return {
            "user": user,
            "conversation": conversation,
            "conversation_started": len(conversation.messages) == 0,
            "execution_context": execution_context,
            "llm_call_counter": execution_context.llm_calls,
            "supervisor_decision": supervisor_decision,
            **routing,
        }

    async def _extract_issues(self, state: AgentState) -> dict:
        request = state["request"]
        correlation_id = state["correlation_id"]
        conversation = state["conversation"]
        ticket_intent = state.get("ticket_intent")
        if ticket_intent is None:
            ticket_intent = await self._resolve_ticket_intent(state)
        superseded_resume = state.get("handoff_resume_reason", "NONE")
        superseded_handoff = superseded_resume in {"NEW_ISSUE", "REVISED_ISSUE"}
        prior_pending_issues = (
            []
            if superseded_handoff
            else _pending_clarifications(conversation)
        )
        decision = state.get("supervisor_decision") or ConversationSupervisorDecision()
        force_ticket_offer = False
        pending_confirmation = False
        if (
            ticket_intent == TicketIntent.NONE
            and not superseded_handoff
            and _has_pending_ticket_offer(conversation)
            and is_pending_ticket_offer_confirmation(request.message.text)
        ):
            ticket_intent = TicketIntent.CREATE
            pending_confirmation = True
        pending_issues = _pending_offer_issues(conversation) if pending_confirmation else []
        active_offer_contexts = (
            []
            if superseded_handoff
            else (
                _recent_ticket_contexts(conversation)
                if ticket_intent == TicketIntent.NONE
                and _has_pending_ticket_offer(conversation)
                and decision.clarificationDisposition == "UNKNOWN"
                else []
            )
        )
        requested_offer_contexts = (
            []
            if superseded_handoff
            else (
                _recent_ticket_contexts(conversation)
                if ticket_intent == TicketIntent.NONE
                and _requests_ticket_offer(request.message.text)
                else []
            )
        )
        if pending_issues:
            # The extractor may recover several outstanding problems from
            # history. A single confirmation authorizes one combined ticket,
            # never one attempt per recovered issue.
            issues = [merge_pending_ticket_issues(pending_issues)]
            too_many_issues = False
        elif active_offer_contexts:
            issues = [
                _pending_context_to_ready_issue(pending, issue_id=index)
                for index, pending in enumerate(active_offer_contexts, start=1)
            ]
            too_many_issues = False
            force_ticket_offer = True
        elif requested_offer_contexts:
            issues = [
                _pending_context_to_ready_issue(pending, issue_id=index)
                for index, pending in enumerate(requested_offer_contexts, start=1)
            ]
            too_many_issues = False
            force_ticket_offer = True
        elif prior_pending_issues and decision.clarificationDisposition == "UNKNOWN":
            # The user cannot provide the requested detail. Stop interrogating
            # and search with the best complete description accumulated so far;
            # never append the literal word "不知道" to the retrieval query.
            issues = [
                _pending_context_to_ready_issue(pending, issue_id=index)
                for index, pending in enumerate(prior_pending_issues, start=1)
            ]
            too_many_issues = False
        else:
            history = await self.conversation_service.get_history(
                conversation.conversationId
            )
            if superseded_resume == "NEW_ISSUE" or ticket_intent == TicketIntent.CANCEL or not _needs_history_for_follow_up(
                conversation
            ):
                history = []
            faq_keys = await asyncio.to_thread(
                self.faq_service.available_keys,
                tuple(request.user.groups),
            )
            outcome = await self.extractor.extract(
                text=request.message.text,
                history=history,
                faq_keys=faq_keys,
                correlation_id=correlation_id,
                presolved_ticket_intent=ticket_intent,
                execution_context=state.get("execution_context"),
            )
            issues = outcome.issues
            if superseded_handoff and decision.intent != "HUMAN_ESCALATION":
                issues = [
                    issue
                    for issue in issues
                    if issue.description != HUMAN_ESCALATION_ISSUE_DESCRIPTION
                ] or issues
            issues = _complete_complementary_pending_issue(
                issues, prior_pending_issues, request.message.text, decision=decision
            )
            too_many_issues = outcome.too_many_issues
            previous_count = max(
                (pending.clarificationCount for pending in prior_pending_issues),
                default=0,
            )
            if previous_count >= self.settings.max_clarification_rounds:
                # The extractor may still ask another reasonable question,
                # but the conversation-level cap wins over per-turn output.
                issues = [
                    issue.model_copy(
                        update={"readiness": "READY", "missingInfo": []}
                    )
                    if issue.readiness == "NEED_MORE_INFO"
                    else issue
                    for issue in issues
                ]
        if (
            ticket_intent == TicketIntent.NONE
            and _is_pending_ticket_detail(prior_pending_issues)
            and any(issue.isIT for issue in issues)
        ):
            issues = [
                issue.model_copy(update={"route": "TICKET"})
                if issue.isIT
                else issue
                for issue in issues
            ]
            if all(
                not issue.isIT or issue.readiness == "READY"
                for issue in issues
            ):
                ticket_intent = TicketIntent.CREATE
        if (
            ticket_intent == TicketIntent.CREATE
            and not pending_confirmation
            and self.settings.ticket_service_mode != "DISABLED"
        ):
            # Explicit create language still needs a short confirmation
            # turn so the user can review before a ticket is opened.
            force_ticket_offer = True
            issues = _issues_for_create_offer(
                issues,
                request.message.text,
                _recent_ticket_contexts(conversation),
            )
            too_many_issues = False
        return {
            "issues": issues,
            "too_many_issues": too_many_issues,
            "ticket_intent": ticket_intent,
            "prior_pending_issues": prior_pending_issues,
            "force_ticket_offer": force_ticket_offer,
        }

    async def _filter_it_issues(self, state: AgentState) -> dict:
        it_issues = [issue for issue in state.get("issues", []) if issue.isIT]
        return {"it_issues": it_issues}
