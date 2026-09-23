"""Issue-extraction path helpers for the clarification workflow."""

from __future__ import annotations

import asyncio
from typing import Any

from .confirmation import TicketIntent, is_pending_ticket_offer_confirmation
from .contracts import AgentRequest, ConversationContext, Issue, PendingIssueContext
from .extractor import HUMAN_ESCALATION_ISSUE_DESCRIPTION, merge_pending_ticket_issues
from .supervisor import ConversationSupervisorDecision
from .workflow_clarification_helpers import (
    _complete_complementary_pending_issue,
    _is_error_catalog_documentation_request,
    _promote_error_catalog_documentation_request,
)
from .workflow_pending_helpers import (
    _has_pending_ticket_offer,
    _is_pending_ticket_detail,
    _issues_for_create_offer,
    _needs_history_for_follow_up,
    _pending_context_to_ready_issue,
    _pending_offer_issues,
    _recent_ticket_contexts,
    _requests_ticket_offer,
)


def resolve_pending_offer_state(
    *,
    request: AgentRequest,
    conversation: ConversationContext,
    ticket_intent: TicketIntent,
    superseded_handoff: bool,
    decision: ConversationSupervisorDecision,
) -> tuple[TicketIntent, bool, list[Issue], list[PendingIssueContext], list[PendingIssueContext]]:
    """Resolve pending-offer confirmation and context lists for extraction."""
    pending_confirmation = False
    catalog_request = _is_error_catalog_documentation_request(request.message.text)
    if (
        ticket_intent == TicketIntent.NONE
        and not superseded_handoff
        and not catalog_request
        and _has_pending_ticket_offer(conversation)
        and is_pending_ticket_offer_confirmation(request.message.text)
    ):
        ticket_intent = TicketIntent.CREATE
        pending_confirmation = True

    pending_issues = _pending_offer_issues(conversation) if pending_confirmation else []
    active_offer_contexts = (
        []
        if superseded_handoff or catalog_request
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
        if superseded_handoff or catalog_request
        else (
            _recent_ticket_contexts(conversation)
            if ticket_intent == TicketIntent.NONE
            and _requests_ticket_offer(request.message.text)
            else []
        )
    )
    return (
        ticket_intent,
        pending_confirmation,
        pending_issues,
        active_offer_contexts,
        requested_offer_contexts,
    )


def issues_from_offer_contexts(
    *,
    pending_issues: list[Issue],
    active_offer_contexts: list[PendingIssueContext],
    requested_offer_contexts: list[PendingIssueContext],
    prior_pending_issues: list[PendingIssueContext],
    decision: ConversationSupervisorDecision,
    latest_text: str = "",
) -> tuple[list[Issue] | None, bool, bool]:
    """Return (issues, too_many, force_offer) when a short-circuit path applies."""
    if _is_error_catalog_documentation_request(latest_text):
        return None, False, False
    if pending_issues:
        return [merge_pending_ticket_issues(pending_issues)], False, False
    if active_offer_contexts:
        issues = [
            _pending_context_to_ready_issue(pending, issue_id=index)
            for index, pending in enumerate(active_offer_contexts, start=1)
        ]
        return issues, False, True
    if requested_offer_contexts:
        issues = [
            _pending_context_to_ready_issue(pending, issue_id=index)
            for index, pending in enumerate(requested_offer_contexts, start=1)
        ]
        return issues, False, True
    if prior_pending_issues and decision.clarificationDisposition == "UNKNOWN":
        issues = [
            _pending_context_to_ready_issue(pending, issue_id=index)
            for index, pending in enumerate(prior_pending_issues, start=1)
        ]
        return issues, False, False
    return None, False, False


def finalize_planned_issues(
    *,
    planned: list[Issue],
    request: AgentRequest,
    prior_pending_issues: list[PendingIssueContext],
    decision: ConversationSupervisorDecision,
    superseded_handoff: bool,
    max_issues_per_message: int,
    max_clarification_rounds: int,
) -> tuple[list[Issue], bool]:
    """Apply handoff/clarification rules to Turn Planner issues (skip extractor)."""
    issues = list(planned)
    too_many_issues = len(planned) > max_issues_per_message
    if superseded_handoff and decision.intent != "HUMAN_ESCALATION":
        issues = [
            issue
            for issue in issues
            if issue.description != HUMAN_ESCALATION_ISSUE_DESCRIPTION
        ] or issues
    issues = _complete_complementary_pending_issue(
        issues, prior_pending_issues, request.message.text, decision=decision
    )
    issues = _promote_error_catalog_documentation_request(
        issues, request.message.text
    )
    previous_count = max(
        (pending.clarificationCount for pending in prior_pending_issues),
        default=0,
    )
    if previous_count >= max_clarification_rounds:
        issues = [
            issue.model_copy(update={"readiness": "READY", "missingInfo": []})
            if issue.readiness == "NEED_MORE_INFO"
            else issue
            for issue in issues
        ]
    return issues, too_many_issues


async def resolve_issues_for_extraction(
    workflow: Any,
    *,
    state: dict[str, Any],
    request: AgentRequest,
    conversation: ConversationContext,
    ticket_intent: TicketIntent,
    superseded_resume: str,
    superseded_handoff: bool,
    prior_pending_issues: list[PendingIssueContext],
    decision: ConversationSupervisorDecision,
) -> tuple[list[Issue], bool]:
    """Prefer Turn Planner issues when enabled; otherwise run the extractor."""
    planned = state.get("planned_issues") or []
    from .turn_planner_policy import resolve_turn_planner_mode

    planner_mode = resolve_turn_planner_mode(
        turn_planner_mode=getattr(workflow.settings, "turn_planner_mode", None),
        turn_planner_enabled=bool(
            getattr(workflow.settings, "turn_planner_enabled", False)
        ),
    )
    if planned and planner_mode != "OFF":
        return finalize_planned_issues(
            planned=planned,
            request=request,
            prior_pending_issues=prior_pending_issues,
            decision=decision,
            superseded_handoff=superseded_handoff,
            max_issues_per_message=workflow.settings.max_issues_per_message,
            max_clarification_rounds=workflow.settings.max_clarification_rounds,
        )
    return await extract_issues_via_extractor(
        workflow,
        request=request,
        conversation=conversation,
        correlation_id=state["correlation_id"],
        ticket_intent=ticket_intent,
        superseded_resume=superseded_resume,
        superseded_handoff=superseded_handoff,
        prior_pending_issues=prior_pending_issues,
        decision=decision,
        execution_context=state.get("execution_context"),
    )


async def extract_issues_via_extractor(
    workflow: Any,
    *,
    request: AgentRequest,
    conversation: ConversationContext,
    correlation_id: str,
    ticket_intent: TicketIntent,
    superseded_resume: str,
    superseded_handoff: bool,
    prior_pending_issues: list[PendingIssueContext],
    decision: ConversationSupervisorDecision,
    execution_context: Any,
) -> tuple[list[Issue], bool]:
    """Run the LLM extractor and apply clarification-completion rules."""
    history = await workflow.conversation_service.get_history(conversation.conversationId)
    if (
        superseded_resume == "NEW_ISSUE"
        or ticket_intent == TicketIntent.CANCEL
        or not _needs_history_for_follow_up(conversation)
    ):
        history = []
    faq_keys = await asyncio.to_thread(
        workflow.faq_service.available_keys,
        tuple(request.user.groups),
    )
    outcome = await workflow.extractor.extract(
        text=request.message.text,
        history=history,
        faq_keys=faq_keys,
        correlation_id=correlation_id,
        conversation_id=conversation.conversationId,
        tenant_id=request.conversation.tenantId,
        presolved_ticket_intent=ticket_intent,
        execution_context=execution_context,
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
    issues = _promote_error_catalog_documentation_request(
        issues, request.message.text
    )
    previous_count = max(
        (pending.clarificationCount for pending in prior_pending_issues),
        default=0,
    )
    if previous_count >= workflow.settings.max_clarification_rounds:
        issues = [
            issue.model_copy(update={"readiness": "READY", "missingInfo": []})
            if issue.readiness == "NEED_MORE_INFO"
            else issue
            for issue in issues
        ]
    return issues, outcome.too_many_issues


def apply_ticket_create_offer(
    workflow: Any,
    *,
    issues: list[Issue],
    request: AgentRequest,
    conversation: ConversationContext,
    ticket_intent: TicketIntent,
    pending_confirmation: bool,
    prior_pending_issues: list[PendingIssueContext],
    force_ticket_offer: bool,
    too_many_issues: bool,
) -> tuple[list[Issue], TicketIntent, bool, bool]:
    """Promote pending ticket detail / explicit create into an offer turn."""
    if (
        ticket_intent == TicketIntent.NONE
        and _is_pending_ticket_detail(prior_pending_issues)
        and any(issue.isIT for issue in issues)
    ):
        issues = [
            issue.model_copy(update={"route": "TICKET"}) if issue.isIT else issue
            for issue in issues
        ]
        if all(not issue.isIT or issue.readiness == "READY" for issue in issues):
            ticket_intent = TicketIntent.CREATE
    if (
        ticket_intent == TicketIntent.CREATE
        and not pending_confirmation
        and workflow._ticket_offers_enabled()
    ):
        force_ticket_offer = True
        issues = _issues_for_create_offer(
            issues,
            request.message.text,
            _recent_ticket_contexts(conversation),
        )
        too_many_issues = False
    return issues, ticket_intent, force_ticket_offer, too_many_issues
