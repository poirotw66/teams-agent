"""Workflow node implementations for the clarification subgraph."""

from __future__ import annotations

import asyncio

from .confirmation import (
    TicketIntent,
    classify_ticket_intent,
)
from .contracts import AgentRequest, ConversationContext
from .execution_context import ExecutionContext
from .graph import user_context_from_identity
from .supervisor import ConversationSupervisorDecision
from .turn_planner import (
    planned_issues_to_issues,
    turn_plan_to_supervisor_decision,
)
from .workflow_helpers import (
    AgentState,
    assistant_scope_issue,
    greeting_issue_from_message,
    non_it_issue_from_message,
)
from .workflow_pending_helpers import (
    _conversation_turns_for_supervisor,
    _has_pending_ticket_offer,
    _pending_clarifications,
)


class ClarificationWorkflowMixin:
    """LangGraph nodes owned by the clarification subgraph."""

    @staticmethod
    def _deterministic_ticket_routing(
        message: str,
    ) -> dict:
        deterministic_intent = classify_ticket_intent(message)
        if deterministic_intent is TicketIntent.QUERY:
            return {"ticket_intent": TicketIntent.QUERY}
        if deterministic_intent is TicketIntent.CREATE:
            return {"ticket_intent": TicketIntent.CREATE}
        return {}

    def _apply_supervisor_routing(
        self,
        conversation: ConversationContext,
        request: AgentRequest,
        decision: ConversationSupervisorDecision,
    ) -> dict:
        """Apply the supervisor LLM decision to LangGraph routing state."""
        routing = self._deterministic_ticket_routing(request.message.text)
        if _pending_clarifications(conversation) or _has_pending_ticket_offer(conversation):
            return routing

        can_terminate = decision.confidence >= self.settings.supervisor_terminal_confidence
        if not can_terminate:
            return routing

        # ASSISTANT_META stays gated by deterministic scope evidence. GREETING
        # may terminate on high confidence alone — social false positives are
        # cheaper than OOS rejects, and regex is only a zero-LLM fast path.
        if decision.intent == "ASSISTANT_META" and not (
            self.supervisor.supports_terminal_intent(
                request.message.text,
                decision.intent,
            )
        ):
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
        teams_conversation_id = request.conversation.conversationId or f"req:{request.requestId}"
        teams_user_id = request.user.teamsUserId or request.user.entraObjectId or "anonymous"
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
        pending_clarification = bool(
            _pending_clarifications(conversation) or _has_pending_ticket_offer(conversation)
        )
        recent_turns = _conversation_turns_for_supervisor(conversation) or None
        planned_issues: list = []
        if self.settings.turn_planner_enabled:
            turn_plan = await self.turn_planner.plan(
                message=request.message.text,
                pending_clarification=pending_clarification,
                recent_turns=recent_turns,
                execution_context=execution_context,
            )
            supervisor_decision = turn_plan_to_supervisor_decision(turn_plan)
            if turn_plan.issues:
                faq_keys = await asyncio.to_thread(
                    self.faq_service.available_keys,
                    tuple(request.user.groups),
                )
                planned_issues = planned_issues_to_issues(
                    turn_plan.issues,
                    raw_utterance=request.message.text,
                    allowed_faq_keys=set(faq_keys),
                    max_missing_info=self.settings.max_missing_info_per_issue,
                )
        else:
            supervisor_decision = await self.supervisor.decide(
                message=request.message.text,
                pending_clarification=pending_clarification,
                recent_turns=recent_turns,
                execution_context=execution_context,
            )
        routing = self._apply_supervisor_routing(conversation, request, supervisor_decision)
        return {
            "user": user,
            "conversation": conversation,
            "conversation_started": len(conversation.messages) == 0,
            "execution_context": execution_context,
            "llm_call_counter": execution_context.llm_calls,
            "supervisor_decision": supervisor_decision,
            "planned_issues": planned_issues,
            **routing,
        }

    async def _extract_issues(self, state: AgentState) -> dict:
        from .workflow_clarification_extract import (
            apply_ticket_create_offer,
            issues_from_offer_contexts,
            resolve_issues_for_extraction,
            resolve_pending_offer_state,
        )

        request = state["request"]
        conversation = state["conversation"]
        ticket_intent = state.get("ticket_intent")
        if ticket_intent is None:
            ticket_intent = await self._resolve_ticket_intent(state)
        superseded_resume = state.get("handoff_resume_reason", "NONE")
        superseded_handoff = superseded_resume in {"NEW_ISSUE", "REVISED_ISSUE"}
        prior_pending_issues = [] if superseded_handoff else _pending_clarifications(conversation)
        decision = state.get("supervisor_decision") or ConversationSupervisorDecision()
        (
            ticket_intent,
            pending_confirmation,
            pending_issues,
            active_offer_contexts,
            requested_offer_contexts,
        ) = resolve_pending_offer_state(
            request=request,
            conversation=conversation,
            ticket_intent=ticket_intent,
            superseded_handoff=superseded_handoff,
            decision=decision,
        )
        issues, too_many_issues, force_ticket_offer = issues_from_offer_contexts(
            pending_issues=pending_issues,
            active_offer_contexts=active_offer_contexts,
            requested_offer_contexts=requested_offer_contexts,
            prior_pending_issues=prior_pending_issues,
            decision=decision,
        )
        if issues is None:
            issues, too_many_issues = await resolve_issues_for_extraction(
                self,
                state=state,
                request=request,
                conversation=conversation,
                ticket_intent=ticket_intent,
                superseded_resume=superseded_resume,
                superseded_handoff=superseded_handoff,
                prior_pending_issues=prior_pending_issues,
                decision=decision,
            )
            force_ticket_offer = False
        issues, ticket_intent, force_ticket_offer, too_many_issues = apply_ticket_create_offer(
            self,
            issues=issues,
            request=request,
            conversation=conversation,
            ticket_intent=ticket_intent,
            pending_confirmation=pending_confirmation,
            prior_pending_issues=prior_pending_issues,
            force_ticket_offer=force_ticket_offer,
            too_many_issues=too_many_issues,
        )
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
