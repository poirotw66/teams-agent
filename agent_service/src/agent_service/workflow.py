"""LangGraph Agent Workflow (spec §5).

This is the primary integration point Task 9 assembles: Load Conversation ->
Extract Issues -> Filter IT Issues -> Process Issues (FAQ | Ask More Info |
Knowledge Search | Ticket Operation) -> Deterministic Response Builder ->
Save Conversation (spec §5.1). It depends only on the interfaces/services
already built by earlier tasks (``FaqService``, ``KnowledgeService``,
``ConversationService``, ``TicketService``, ``IssueExtractor``,
``response_builder.build_response``) — never on a concrete database,
retrieval product or ticket backend (spec §3.2).

Correlation ID (spec §15.1)
----------------------------
Derived exactly ONCE, by the caller of :meth:`AgentWorkflow.run` (typically
``api.py``, the actual Teams-request entry point) or, if none is supplied,
by ``run`` itself from ``request.correlationId`` / the logical request identity. It is
placed into ``AgentState["correlation_id"]`` before the graph starts and
every node only *reads* it, so the
same id reaches the extractor, the knowledge service, the ticket service and
the conversation repository.

Ticket intent guardrail
-----------------------
Ticket operations are selected from the current message by
``classify_ticket_intent`` with a fixed ``CANCEL > QUERY > CREATE > NONE``
precedence.  The LLM's extracted route is never allowed to override that
guardrail: cancellation is a direct acknowledgement, creation/query use only
the matching Ticket Service operation, and NONE cannot call Ticket Service.
This makes a cancellation terminal for the turn and prevents a later bare
"是" from reviving an earlier offer.

Non-blocking processing (spec §4.2)
--------------------------------------
Every IT issue is processed concurrently via ``asyncio.gather(...,
return_exceptions=True)``, wrapped in a per-issue try/except besides. One
issue's exception becomes a ``FAILED`` IssueResult (with the error kept out
of the user-facing text — response_builder never renders
``IssueResult.error``) and never stops the others.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from .contracts import AgentRequest, AgentResponse
from .conversation import ConversationService
from .extractor import IssueExtractor
from .faq import FaqService
from .handoff import HandoffRepository
from .handoff_flow import AgenticHandoffRouter
from .knowledge import KnowledgeService
from .operations.event_identity import LogicalRequestIdentity
from .settings import RagSettings
from .supervisor import ConversationSupervisor
from .ticket import AgenticTicketItemSelector, TicketService
from .ticket_dedupe import InMemoryTicketRequestDedupeRepository, TicketRequestDedupeRepository
from .workflow_clarification import ClarificationWorkflowMixin
from .workflow_handoff_nodes import HandoffWorkflowMixin
from .workflow_helpers import (
    INITIAL_STAGE_LABEL,
    STAGE_LABELS,
    AgentState,
    _knowledge_search_supports_call_counter,
    build_knowledge_service,
)
from .workflow_issue_processing import IssueProcessingWorkflowMixin
from .workflow_response import ResponseWorkflowMixin
from .workflow_subgraphs import build_agent_workflow_graph

__all__ = [
    "INITIAL_STAGE_LABEL",
    "STAGE_LABELS",
    "AgentState",
    "AgentWorkflow",
    "WorkflowServices",
    "build_knowledge_service",
]


class AgentWorkflow(
    ClarificationWorkflowMixin,
    HandoffWorkflowMixin,
    IssueProcessingWorkflowMixin,
    ResponseWorkflowMixin,
):
    """LangGraph workflow implementing spec §5.1's node pipeline."""

    def __init__(
        self,
        settings: RagSettings,
        *,
        extractor: IssueExtractor,
        faq_service: FaqService,
        knowledge_service: KnowledgeService,
        conversation_service: ConversationService,
        ticket_service: TicketService,
        handoff_repository: HandoffRepository | None = None,
        handoff_router: AgenticHandoffRouter | None = None,
        ticket_item_selector: AgenticTicketItemSelector | None = None,
        ticket_request_dedupe: TicketRequestDedupeRepository | None = None,
    ) -> None:
        self.settings = settings
        self.extractor = extractor
        self.faq_service = faq_service
        self.knowledge_service = knowledge_service
        self.conversation_service = conversation_service
        self.ticket_service = ticket_service
        self.handoff_repository = handoff_repository
        self.handoff_router = handoff_router or AgenticHandoffRouter(extractor.model)
        self.ticket_item_selector = ticket_item_selector or AgenticTicketItemSelector(
            extractor.model
        )
        self.supervisor = ConversationSupervisor(extractor.model)
        self.ticket_request_dedupe = (
            ticket_request_dedupe or InMemoryTicketRequestDedupeRepository()
        )
        from .prompt_runtime import GovernanceRuntime

        self.governance_runtime = GovernanceRuntime.from_settings(settings)
        self._knowledge_supports_counter = _knowledge_search_supports_call_counter(
            knowledge_service
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        return build_agent_workflow_graph(AgentState, self)

    def _initial_state(
        self, request: AgentRequest, correlation_id: str | None
    ) -> AgentState:
        resolved_correlation_id = correlation_id or request.correlationId
        if not resolved_correlation_id:
            resolved_correlation_id = LogicalRequestIdentity(
                request.conversation.tenantId,
                request.conversation.conversationId,
                request.requestId,
            ).value
        return {
            "request": request,
            "correlation_id": resolved_correlation_id,
            "issues": [],
            "it_issues": [],
            "issue_results": [],
            "too_many_issues": False,
            "final_response": "",
            "citations": [],
            "images": [],
            "feedback_enabled": False,
            "prior_pending_issues": [],
            "force_ticket_offer": False,
            "handoff_handled": False,
            "handoff_resume_reason": "NONE",
        }

    async def run(
        self, request: AgentRequest, *, correlation_id: str | None = None
    ) -> AgentState:
        result: AgentState = await self.graph.ainvoke(
            self._initial_state(request, correlation_id)
        )
        return result

    @staticmethod
    def _to_response(state: AgentState) -> AgentResponse:
        return AgentResponse(
            answer=state.get("final_response", ""),
            traceId=state["correlation_id"],
            correlationId=state["correlation_id"],
            citations=state.get("citations", []),
            images=state.get("images", []),
            issueResults=state.get("issue_results", []),
            feedbackEnabled=state.get("feedback_enabled", False),
        )

    async def respond(
        self, request: AgentRequest, *, correlation_id: str | None = None
    ) -> AgentResponse:
        return self._to_response(await self.run(request, correlation_id=correlation_id))

    async def stream(
        self, request: AgentRequest, *, correlation_id: str | None = None
    ) -> AsyncIterator[tuple[str, Any]]:
        state: AgentState = self._initial_state(request, correlation_id)

        async for update in self.graph.astream(dict(state), stream_mode="updates"):
            if not isinstance(update, dict):
                continue
            for node_name, delta in update.items():
                if isinstance(delta, dict):
                    state.update(delta)  # type: ignore[typeddict-item]
                label = STAGE_LABELS.get(node_name)
                if label:
                    yield "stage", label

        yield "state", state


@dataclass(frozen=True)
class WorkflowServices:
    """Bundle of collaborators an :class:`AgentWorkflow` needs.

    Purely a constructor-argument convenience for ``api.py``'s lifespan
    wiring; not used internally by the workflow itself.
    """

    extractor: IssueExtractor
    faq_service: FaqService
    knowledge_service: KnowledgeService
    conversation_service: ConversationService
    ticket_service: TicketService
