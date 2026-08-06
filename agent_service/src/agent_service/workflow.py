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
by ``run`` itself from ``request.correlationId`` / a fresh uuid4. It is
placed into ``AgentState["correlation_id"]`` before the graph starts and
every node only *reads* it — no node ever calls ``uuid4()`` again — so the
same id reaches the extractor, the knowledge service, the ticket service and
the conversation repository.

Pending-ticket state (spec §3.3, §11.3)
-----------------------------------------
Spec §3.3 forbids building a full Issue Repository / ticket lifecycle just
to remember "was a ticket offered". Instead of persisting anything new, a
turn is treated as replying to a pending ticket offer when EITHER:

1. The just-loaded conversation history's last message is from the
   assistant and contains the literal marker substring
   ``"是否需要協助建立工單"`` — the exact offer sentence
   ``response_builder._render_no_knowledge`` appends after a NO_KNOWLEDGE
   result when ticket offering is enabled. This covers a user's bare
   follow-up ("好，幫我開單") after a *previous* turn's offer.
2. The current issue's own ``route`` is already ``"TICKET"`` — i.e. the
   Issue Extractor itself recognised this message as an explicit request to
   create/check a ticket (spec §11.3's fourth trigger, "使用者主動要求建立
   工單"), so the offer and the confirmation arrive in the very same turn
   (e.g. "請幫我建立工單" as the *first* message).

Either way, ticket CREATION additionally always requires
``is_explicit_ticket_confirmation(text)`` to be true (spec §11.3: 未經明確確認
不得建立工單) — the pending-offer check only establishes there was a valid
reason to be listening for a confirmation in the first place; a hedge
("可能要報修") is never treated as a confirmation regardless of context.

Non-blocking processing (spec §4.2)
--------------------------------------
Every IT issue is processed concurrently via ``asyncio.gather(...,
return_exceptions=True)``, wrapped in a per-issue try/except besides. One
issue's exception becomes a ``FAILED`` IssueResult (with the error kept out
of the user-facing text — response_builder never renders
``IssueResult.error``) and never stops the others.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .confirmation import is_explicit_ticket_confirmation
from .contracts import (
    AgentImage,
    AgentRequest,
    AgentResponse,
    Citation,
    ConversationContext,
    Issue,
    IssueResult,
    TicketDraft,
    UserContext,
)
from .conversation import ConversationService
from .extractor import IssueExtractor
from .faq import FaqService
from .graph import user_context_from_identity
from .knowledge import KnowledgeService, LlmCallCounter
from .response_builder import build_response
from .retrieval import HybridIndex
from .settings import RagSettings
from .ticket import (
    TicketService,
    TicketServiceDisabledError,
    TicketServiceError,
    TicketServiceTimeout,
    UntrustedRequesterError,
)

logger = logging.getLogger(__name__)

# See module docstring "Pending-ticket state" for why this literal is
# matched instead of persisting extra state. Kept in sync with the exact
# Chinese copy in response_builder._render_no_knowledge.
_TICKET_OFFER_MARKER = "是否需要協助建立工單"


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
    final_response: str
    citations: list[Citation]
    images: list[AgentImage]
    feedback_enabled: bool


def _has_pending_ticket_offer(conversation: ConversationContext) -> bool:
    if not conversation.messages:
        return False
    last = conversation.messages[-1]
    return last.role == "assistant" and _TICKET_OFFER_MARKER in last.text


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
) -> KnowledgeService:
    """Single factory honoring ``settings.knowledge_service_mode`` (spec §8.2/§8.3).

    This is the ONE place the mode switch lives; nothing else in the
    workflow (or ``api.py``) branches on ``knowledge_service_mode``.
    """
    from .knowledge import HybridKnowledgeService

    if settings.knowledge_service_mode == "GEMINI_FILE_SEARCH":
        from .gemini_file_search import GeminiFileSearchKnowledgeService

        logger.warning(
            "KNOWLEDGE_SERVICE_MODE=GEMINI_FILE_SEARCH selected; this is a "
            "spike-only adapter, not the validated default (spec §8.3)."
        )
        return GeminiFileSearchKnowledgeService(
            api_key=None,
            file_search_store=settings.gemini_file_search_store or "",
            model=settings.model or "gemini-2.5-flash",
            top_k=settings.top_k,
        )
    return HybridKnowledgeService(settings, index, model)


class AgentWorkflow:
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
    ) -> None:
        self.settings = settings
        self.extractor = extractor
        self.faq_service = faq_service
        self.knowledge_service = knowledge_service
        self.conversation_service = conversation_service
        self.ticket_service = ticket_service
        self._knowledge_supports_counter = _knowledge_search_supports_call_counter(
            knowledge_service
        )
        self.graph = self._build_graph()

    # --- graph wiring ----------------------------------------------

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("load_conversation", self._load_conversation)
        builder.add_node("extract_issues", self._extract_issues)
        builder.add_node("filter_it_issues", self._filter_it_issues)
        builder.add_node("process_issues", self._process_issues)
        builder.add_node("build_response", self._build_response)
        builder.add_node("save_conversation", self._save_conversation)

        builder.add_edge(START, "load_conversation")
        builder.add_edge("load_conversation", "extract_issues")
        builder.add_edge("extract_issues", "filter_it_issues")
        builder.add_edge("filter_it_issues", "process_issues")
        builder.add_edge("process_issues", "build_response")
        builder.add_edge("build_response", "save_conversation")
        builder.add_edge("save_conversation", END)
        return builder.compile()

    # --- nodes -------------------------------------------------------

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
        return {"user": user, "conversation": conversation}

    async def _extract_issues(self, state: AgentState) -> dict:
        request = state["request"]
        correlation_id = state["correlation_id"]
        conversation = state["conversation"]
        history = await self.conversation_service.get_history(conversation.conversationId)
        faq_keys = self.faq_service.available_keys()
        outcome = await self.extractor.extract(
            text=request.message.text,
            history=history,
            faq_keys=faq_keys,
            correlation_id=correlation_id,
        )
        counter = LlmCallCounter(count=outcome.llm_calls)
        return {
            "issues": outcome.issues,
            "too_many_issues": outcome.too_many_issues,
            "llm_call_counter": counter,
        }

    async def _filter_it_issues(self, state: AgentState) -> dict:
        it_issues = [issue for issue in state.get("issues", []) if issue.isIT]
        return {"it_issues": it_issues}

    async def _process_issues(self, state: AgentState) -> dict:
        request = state["request"]
        correlation_id = state["correlation_id"]
        user = state["user"]
        conversation = state["conversation"]
        counter = state["llm_call_counter"]
        it_issues = state.get("it_issues", [])

        lock = asyncio.Lock()
        ticket_created = {"done": False}
        pending_offer = _has_pending_ticket_offer(conversation)

        async def handle(issue: Issue) -> IssueResult:
            try:
                return await self._handle_issue(
                    issue,
                    request=request,
                    user=user,
                    correlation_id=correlation_id,
                    counter=counter,
                    lock=lock,
                    ticket_created=ticket_created,
                    pending_offer=pending_offer,
                )
            except Exception as exc:  # noqa: BLE001 - one issue must never sink the rest
                logger.error(
                    "Issue processing failed: issue_id=%s error_type=%s correlation_id=%s",
                    issue.id,
                    type(exc).__name__,
                    correlation_id,
                )
                return IssueResult(
                    issueId=issue.id,
                    resultType="FAILED",
                    error=f"{type(exc).__name__}: {exc}"[:300],
                )

        gathered = await asyncio.gather(
            *(handle(issue) for issue in it_issues), return_exceptions=True
        )
        issue_results: list[IssueResult] = []
        for issue, outcome in zip(it_issues, gathered, strict=True):
            if isinstance(outcome, BaseException):
                logger.error(
                    "Issue processing raised unexpectedly: issue_id=%s error_type=%s "
                    "correlation_id=%s",
                    issue.id,
                    type(outcome).__name__,
                    correlation_id,
                )
                issue_results.append(
                    IssueResult(
                        issueId=issue.id,
                        resultType="FAILED",
                        error=type(outcome).__name__[:300],
                    )
                )
            else:
                issue_results.append(outcome)
        return {"issue_results": issue_results}

    async def _handle_issue(
        self,
        issue: Issue,
        *,
        request: AgentRequest,
        user: UserContext,
        correlation_id: str,
        counter: LlmCallCounter,
        lock: asyncio.Lock,
        ticket_created: dict,
        pending_offer: bool,
    ) -> IssueResult:
        if issue.readiness == "NEED_MORE_INFO":
            return IssueResult(
                issueId=issue.id,
                resultType="NEED_MORE_INFO",
                questions=issue.missingInfo,
            )

        text = request.message.text
        if (
            pending_offer
            and issue.route != "TICKET"
            and is_explicit_ticket_confirmation(text)
        ):
            # A bare follow-up ("好，幫我開單") answering a PREVIOUS turn's
            # ticket offer, even though the extractor didn't re-tag this
            # issue's route as TICKET (spec §11.3 pending-offer path; see
            # module docstring).
            return await self._handle_ticket(
                issue,
                request=request,
                user=user,
                correlation_id=correlation_id,
                lock=lock,
                ticket_created=ticket_created,
                pending_offer=pending_offer,
            )

        if issue.route == "FAQ":
            entry = self.faq_service.get(issue.faqKey) if issue.faqKey else None
            if entry is not None:
                # Spec §7.3: FAQ answer used VERBATIM. No LLM, no rewriting.
                return IssueResult(
                    issueId=issue.id,
                    resultType="FAQ_ANSWERED",
                    answer=entry.answer,
                    backend="FAQ",
                )
            # Miss or disabled entry falls back to KNOWLEDGE, never fails.
            return await self._handle_knowledge(issue, user, correlation_id, counter, lock)

        if issue.route == "KNOWLEDGE":
            return await self._handle_knowledge(issue, user, correlation_id, counter, lock)

        if issue.route == "TICKET":
            return await self._handle_ticket(
                issue,
                request=request,
                user=user,
                correlation_id=correlation_id,
                lock=lock,
                ticket_created=ticket_created,
                pending_offer=pending_offer,
            )

        # Defensive fallback: NOT_IT issues are filtered out before this
        # point (Filter IT Issues node), so this should be unreachable.
        return IssueResult(issueId=issue.id, resultType="FAILED", error="unexpected_route")

    async def _handle_knowledge(
        self,
        issue: Issue,
        user: UserContext,
        correlation_id: str,
        counter: LlmCallCounter,
        lock: asyncio.Lock,
    ) -> IssueResult:
        async with lock:
            budget_exceeded = counter.count >= self.settings.max_llm_calls_per_request

        if budget_exceeded:
            # Spec §16: stop making further LLM calls and degrade gracefully
            # rather than raising.
            logger.warning(
                "LLM call budget exceeded, degrading issue to NO_KNOWLEDGE: "
                "issue_id=%s correlation_id=%s",
                issue.id,
                correlation_id,
            )
            return IssueResult(
                issueId=issue.id, resultType="NO_KNOWLEDGE", backend="BUDGET_EXCEEDED"
            )

        if self._knowledge_supports_counter:
            result = await self.knowledge_service.search(
                issue.description,
                user,
                correlation_id=correlation_id,
                call_counter=counter,
            )
        else:
            result = await self.knowledge_service.search(
                issue.description, user, correlation_id=correlation_id
            )
            async with lock:
                counter.increment()

        if result.found:
            return IssueResult(
                issueId=issue.id,
                resultType="KNOWLEDGE_ANSWERED",
                answer=result.answer,
                sources=result.sources,
                images=result.images,
                backend=result.backend,
            )
        return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE", backend=result.backend)

    async def _handle_ticket(
        self,
        issue: Issue,
        *,
        request: AgentRequest,
        user: UserContext,
        correlation_id: str,
        lock: asyncio.Lock,
        ticket_created: dict,
        pending_offer: bool,
    ) -> IssueResult:
        text = request.message.text
        wants_create = is_explicit_ticket_confirmation(text) and (
            issue.route == "TICKET" or pending_offer
        )

        if not wants_create:
            return await self._query_tickets(issue, user, correlation_id)

        # Spec §11.4: identity must come ONLY from the trusted Teams/Entra
        # context, never from the user's free text.
        if not user.is_trusted_for_ticket:
            logger.warning(
                "Ticket creation refused: untrusted requester identity. "
                "issue_id=%s correlation_id=%s",
                issue.id,
                correlation_id,
            )
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")

        # Spec §11.5: at most one ticket created per turn.
        async with lock:
            if ticket_created["done"]:
                allowed = False
            else:
                ticket_created["done"] = True
                allowed = True
        if not allowed:
            logger.info(
                "Ticket creation skipped: one-ticket-per-turn limit already reached. "
                "issue_id=%s correlation_id=%s",
                issue.id,
                correlation_id,
            )
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_limit_per_turn"
            )

        requester_id = user.entraObjectId or user.teamsUserId or ""
        try:
            items = await self.ticket_service.get_ticket_items(correlation_id=correlation_id)
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        item_id = items[0].id if items else "GENERAL"
        draft = TicketDraft(
            requesterId=requester_id,
            requesterName=user.displayName or "",
            requesterEmail=user.email or "",
            title=issue.description[:120],
            description=issue.description,
            ticketItemId=item_id,
        )
        try:
            ticket = await self.ticket_service.create_ticket(draft, correlation_id=correlation_id)
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except UntrustedRequesterError:
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        sources = [Citation(title=f"{ticket.title} ({ticket.status})", url=ticket.url)]
        return IssueResult(
            issueId=issue.id, resultType="TICKET_CREATED", ticketId=ticket.id, sources=sources
        )

    async def _query_tickets(
        self, issue: Issue, user: UserContext, correlation_id: str
    ) -> IssueResult:
        # Spec §17: never allow querying another user's tickets — always
        # scope strictly to the trusted current-user id.
        requester_id = user.entraObjectId or user.teamsUserId
        if not requester_id:
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")
        try:
            tickets = await self.ticket_service.list_tickets_by_requester(
                requester_id, correlation_id=correlation_id
            )
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        sources = [Citation(title=f"{t.title} ({t.status})", url=t.url) for t in tickets]
        return IssueResult(issueId=issue.id, resultType="TICKET_FOUND", sources=sources)

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
        )
        return {}

    # --- entry points --------------------------------------------------

    async def run(
        self, request: AgentRequest, *, correlation_id: str | None = None
    ) -> AgentState:
        # Spec §15.1: derived exactly once, never regenerated between nodes.
        resolved_correlation_id = correlation_id or request.correlationId or str(uuid.uuid4())
        initial_state: AgentState = {
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
        }
        result: AgentState = await self.graph.ainvoke(initial_state)
        return result

    async def respond(
        self, request: AgentRequest, *, correlation_id: str | None = None
    ) -> AgentResponse:
        result = await self.run(request, correlation_id=correlation_id)
        return AgentResponse(
            answer=result.get("final_response", ""),
            traceId=result["correlation_id"],
            correlationId=result["correlation_id"],
            citations=result.get("citations", []),
            images=result.get("images", []),
            issueResults=result.get("issue_results", []),
            feedbackEnabled=result.get("feedback_enabled", False),
        )


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
