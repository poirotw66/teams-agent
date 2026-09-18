"""Shared workflow state, stage labels, issue factories, and knowledge factory."""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from typing import TypedDict

from .confirmation import TicketIntent
from .contracts import (
    AgentImage,
    AgentRequest,
    Citation,
    ConversationContext,
    ConversationMessage,
    Issue,
    IssueResult,
    PendingIssueContext,
    UserContext,
)
from .execution_context import ExecutionContext
from .handoff import HandoffCase
from .knowledge import KnowledgeService, LlmCallCounter
from .retrieval import HybridIndex
from .sanitize import sanitize_description
from .settings import RagSettings
from .supervisor import ConversationSupervisorDecision

logger = logging.getLogger(__name__)

# Progress stages surfaced to the Teams user while the graph runs (spec §5.1
# node boundaries, reused as user-visible progress).
#
# The mapping is keyed by the node that just FINISHED and names the work that
# is now starting, because `graph.astream` emits an update only once a node
# completes. `save_conversation` is deliberately absent: by the time it runs
# the answer is already known, and the Teams Adapter finalizes the streamed
# message rather than showing another status line.
#
# These are the only user-visible strings in this module. Everything else the
# user reads is rendered by `response_builder`.
STAGE_LABELS: dict[str, str] = {
    "load_conversation": "正在理解你的問題…",
    "extract_issues": "正在確認問題類型…",
    "filter_it_issues": "正在檢索知識庫…",
    "process_issues": "正在整理答案…",
}
# Sent before the graph starts, so the user sees something within one Teams
# round-trip rather than waiting for the first node to finish.
INITIAL_STAGE_LABEL = "已收到你的問題…"


def non_it_issue_from_message(text: str, *, issue_id: int = 1) -> Issue:
    """Build a NOT_IT issue from the user's current turn without an extractor LLM call."""
    description = sanitize_description(text.strip())[:4000]
    return Issue(
        id=issue_id,
        description=description,
        isIT=False,
        readiness="NOT_IT",
        route="NOT_IT",
        missingInfo=[],
        faqKey=None,
        ticketAction=None,
    )


def assistant_scope_issue(*, issue_id: int = 1) -> Issue:
    return Issue(
        id=issue_id,
        description="IT 服務範圍與小幫手功能介紹",
        isIT=False,
        readiness="NOT_IT",
        route="NOT_IT",
        missingInfo=[],
        faqKey=None,
        ticketAction=None,
    )


def greeting_issue_from_message(text: str, *, issue_id: int = 1) -> Issue:
    """Build a GREETING issue from the user's current turn without an extractor LLM call."""
    description = sanitize_description(text.strip())[:4000]
    return Issue(
        id=issue_id,
        description=description,
        isIT=False,
        readiness="GREETING",
        route="GREETING",
        missingInfo=[],
        faqKey=None,
        ticketAction=None,
    )


class AgentState(TypedDict, total=False):
    """Workflow state (spec §5.2), plus a few documented workflow-only fields.

    Spec-mandated fields: ``request``, ``correlation_id``, ``user``,
    ``conversation``, ``issues``, ``issue_results``, ``final_response``.

    Added fields (all workflow-internal plumbing, never part of the spec's
    literal state shape, but needed to keep node functions pure/composable):

    - ``it_issues``: the IT-only subset of ``issues`` computed by the
      "Filter IT Issues" node, so "Process Issues" doesn't recompute it and
      the node boundary from the spec diagram (§5.1) is real, not just a
      naming convention.
    - ``too_many_issues``: propagated from the Issue Extractor (spec §4.2)
      so the Response Builder can render the "please prioritize" notice.
    - ``llm_call_counter``: a single ``LlmCallCounter`` (from ``knowledge.py``)
      shared across the extractor's own call count and every Knowledge
      Service call made while processing issues, so spec §16's
      ``MAX_LLM_CALLS_PER_REQUEST`` is enforced per-*request*, not
      per-component.
    - ``citations`` / ``images`` / ``feedback_enabled``: the rest of what
      the deterministic Response Builder produces (``final_response`` only
      covers the rendered text; ``AgentResponse`` needs the rest too).
    """

    request: AgentRequest
    correlation_id: str
    user: UserContext
    conversation: ConversationContext
    issues: list[Issue]
    it_issues: list[Issue]
    issue_results: list[IssueResult]
    too_many_issues: bool
    llm_call_counter: LlmCallCounter
    execution_context: ExecutionContext
    final_response: str
    citations: list[Citation]
    images: list[AgentImage]
    feedback_enabled: bool
    ticket_intent: TicketIntent
    prior_pending_issues: list[PendingIssueContext]
    force_ticket_offer: bool
    handoff_case: HandoffCase
    handoff_handled: bool
    handoff_resume_reason: str
    supervisor_decision: ConversationSupervisorDecision
    skip_issue_pipeline: bool
    operational_user_message: ConversationMessage
    operational_occurred_at: datetime
    operational_conversation_started_at: datetime


def _knowledge_search_supports_call_counter(knowledge_service: KnowledgeService) -> bool:
    try:
        signature = inspect.signature(knowledge_service.search)
    except (TypeError, ValueError):  # pragma: no cover - defensive only
        return False
    return "call_counter" in signature.parameters


def build_knowledge_service(
    settings: RagSettings,
    index: HybridIndex,
    model=None,
    release_id: str | None = None,
) -> KnowledgeService:
    """Single factory honoring ``settings.knowledge_service_mode`` (spec §8.2/§8.3).

    This is the ONE place the mode switch lives; nothing else in the
    workflow (or ``api.py``) branches on ``knowledge_service_mode``.
    """
    from .knowledge import HybridKnowledgeService

    if settings.knowledge_service_mode == "GEMINI_FILE_SEARCH":
        from .file_search_registry import FileSearchDocumentRegistry
        from .gemini_file_search import GeminiFileSearchKnowledgeService

        logger.warning(
            "KNOWLEDGE_SERVICE_MODE=GEMINI_FILE_SEARCH selected; this is a "
            "spike-only adapter, not the validated default (spec §8.3)."
        )
        return GeminiFileSearchKnowledgeService(
            api_key=None,
            file_search_store=settings.gemini_file_search_store or "",
            model=settings.gemini_file_search_model,
            top_k=settings.top_k,
            registry=FileSearchDocumentRegistry.from_chunks(index.chunks),
            max_images=settings.max_images,
            enforce_acl=settings.gemini_file_search_enforce_acl,
        )
    return HybridKnowledgeService(settings, index, model, release_id=release_id)
