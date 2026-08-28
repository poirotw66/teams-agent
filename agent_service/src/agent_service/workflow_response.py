"""Workflow node implementations for the response subgraph."""

from __future__ import annotations

from .contracts import PendingIssueContext
from .response_builder import build_response
from .workflow_helpers import (
    _TICKET_OFFER_MARKER,
    AgentState,
    _preserves_interrupted_clarification,
)


class ResponseWorkflowMixin:
    """LangGraph nodes owned by the response subgraph."""

    async def _build_response(self, state: AgentState) -> dict:
        # Spec §5.3: deterministic template only, no LLM call from here on.
        offer_ticket = self.settings.ticket_service_mode != "DISABLED"
        built = build_response(
            issues=state.get("issues", []),
            results=state.get("issue_results", []),
            too_many_issues=state.get("too_many_issues", False),
            settings=self.settings,
            offer_ticket_on_no_knowledge=offer_ticket,
            correlation_id=state["correlation_id"],
        )
        return {
            "final_response": built.text,
            "citations": built.citations,
            "images": built.images,
            "feedback_enabled": built.feedback_enabled,
        }

    async def _save_conversation(self, state: AgentState) -> dict:
        request = state["request"]
        conversation = state["conversation"]
        correlation_id = state["correlation_id"]
        pending_issues = self._pending_issues_for_next_turn(state)
        await self.conversation_service.record_message(
            conversation.conversationId,
            role="user",
            text=request.message.text,
            correlation_id=correlation_id,
        )
        await self.conversation_service.record_message(
            conversation.conversationId,
            role="assistant",
            text=state.get("final_response", ""),
            correlation_id=correlation_id,
            follow_up_state=self._follow_up_state(state, pending_issues),
            pending_issues=pending_issues,
        )
        return {}

    @staticmethod
    def _pending_issues_for_next_turn(
        state: AgentState,
    ) -> list[PendingIssueContext]:
        issues_by_id = {issue.id: issue for issue in state.get("issues", [])}
        prior = state.get("prior_pending_issues", [])
        previous_count = max(
            (pending.clarificationCount for pending in prior), default=0
        )
        previous_questions = [
            question
            for pending in prior
            for question in pending.askedQuestions
        ]
        pending_contexts: list[PendingIssueContext] = []
        if _preserves_interrupted_clarification(state):
            return list(prior)
        for result in state.get("issue_results", []):
            issue = issues_by_id.get(result.issueId)
            if issue is None:
                continue
            if result.resultType == "NEED_MORE_INFO":
                asked_questions = list(
                    dict.fromkeys([*previous_questions, *result.questions])
                )
                pending_contexts.append(
                    PendingIssueContext(
                        description=issue.description,
                        contextText=(
                            prior[0].contextText
                            if len(prior) == 1 and prior[0].contextText
                            else state["request"].message.text
                        ),
                        route=issue.route,
                        faqKey=issue.faqKey,
                        missingInfo=result.questions,
                        askedQuestions=asked_questions,
                        clarificationCount=previous_count + 1,
                    )
                )
            elif (
                result.resultType == "NO_KNOWLEDGE"
                and _TICKET_OFFER_MARKER in state.get("final_response", "")
            ):
                pending_contexts.append(
                    PendingIssueContext(
                        description=issue.description,
                        route="KNOWLEDGE",
                    )
                )
            elif result.resultType in {"KNOWLEDGE_ANSWERED", "FAQ_ANSWERED"}:
                pending_contexts.append(
                    PendingIssueContext(
                        description=issue.description,
                        route=issue.route,
                        faqKey=issue.faqKey,
                    )
                )
        return pending_contexts

    @staticmethod
    def _follow_up_state(
        state: AgentState, pending_issues: list[PendingIssueContext]
    ) -> str:
        if any(
            result.resultType == "NEED_MORE_INFO"
            for result in state.get("issue_results", [])
        ):
            return "AWAITING_CLARIFICATION"
        if pending_issues and _preserves_interrupted_clarification(state):
            return "AWAITING_CLARIFICATION"
        if _TICKET_OFFER_MARKER in state.get("final_response", ""):
            return "AWAITING_TICKET_CONFIRMATION"
        return "NONE"
