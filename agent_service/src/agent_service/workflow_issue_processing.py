"""Workflow node implementations for the issue processing subgraph."""

from __future__ import annotations

import asyncio
import inspect
import logging

from .confirmation import TicketIntent
from .contracts import AgentRequest, Citation, Issue, IssueResult, TicketDraft, UserContext
from .execution_context import ExecutionContext
from .extractor import HUMAN_ESCALATION_ISSUE_DESCRIPTION
from .knowledge import LlmCallCounter
from .ticket import (
    TicketServiceDisabledError,
    TicketServiceError,
    TicketServiceTimeout,
    UntrustedRequesterError,
    handoff_ticket_item_fallback,
)
from .workflow_helpers import AgentState

logger = logging.getLogger(__name__)


class IssueProcessingWorkflowMixin:
    """LangGraph nodes owned by the issue processing subgraph."""

    async def _process_issues(self, state: AgentState) -> dict:
        correlation_id = state["correlation_id"]
        user = state["user"]
        counter = state["llm_call_counter"]
        it_issues = state.get("it_issues", [])
        ticket_intent = state.get("ticket_intent", TicketIntent.NONE)

        lock = asyncio.Lock()
        ticket_created = {"done": False}

        async def handle(issue: Issue) -> IssueResult:
            try:
                if state.get("force_ticket_offer", False):
                    if issue.readiness == "NEED_MORE_INFO":
                        return IssueResult(
                            issueId=issue.id,
                            resultType="NEED_MORE_INFO",
                            questions=issue.missingInfo,
                        )
                    return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE")
                return await self._handle_issue(
                    issue,
                    user=user,
                    correlation_id=correlation_id,
                    counter=counter,
                    lock=lock,
                    ticket_created=ticket_created,
                    ticket_intent=ticket_intent,
                    request_id=state["request"].requestId,
                    tenant_id=state["request"].conversation.tenantId,
                    agent_request=state["request"],
                    idempotency_key=state.get("execution_context").idempotency_key
                    if state.get("execution_context")
                    else None,
                    execution_context=state.get("execution_context"),
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
        user: UserContext,
        correlation_id: str,
        counter: LlmCallCounter,
        lock: asyncio.Lock,
        ticket_created: dict,
        ticket_intent: TicketIntent,
        request_id: str | None = None,
        tenant_id: str | None = None,
        agent_request: AgentRequest | None = None,
        idempotency_key: str | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> IssueResult:
        if ticket_intent == TicketIntent.DELETE_DENIED:
            return IssueResult(issueId=issue.id, resultType="TICKET_DELETE_DENIED")

        if ticket_intent == TicketIntent.CANCEL:
            return IssueResult(issueId=issue.id, resultType="TICKET_CANCELLED")

        if ticket_intent in {TicketIntent.CREATE, TicketIntent.QUERY}:
            return await self._handle_ticket(
                issue,
                user=user,
                correlation_id=correlation_id,
                lock=lock,
                ticket_created=ticket_created,
                ticket_intent=ticket_intent,
                request_id=request_id,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                execution_context=execution_context,
            )

        if issue.readiness == "NEED_MORE_INFO":
            return IssueResult(
                issueId=issue.id,
                resultType="NEED_MORE_INFO",
                questions=issue.missingInfo,
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
            return await self._handle_knowledge(
                issue, user, correlation_id, counter, lock, agent_request=agent_request
            )

        if issue.route == "KNOWLEDGE":
            return await self._handle_knowledge(
                issue, user, correlation_id, counter, lock, agent_request=agent_request
            )

        if issue.route == "TICKET":
            # Defense in depth: extractor routes are advisory.  A message
            # with no deterministic ticket intent must not call Ticket API.
            return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE")

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
        *,
        agent_request: AgentRequest | None = None,
    ) -> IssueResult:
        if issue.description == HUMAN_ESCALATION_ISSUE_DESCRIPTION:
            return IssueResult(
                issueId=issue.id,
                resultType="NO_KNOWLEDGE",
                backend="ESCALATION",
            )

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

        search_kwargs: dict[str, object] = {
            "correlation_id": correlation_id,
        }
        if self._knowledge_supports_counter:
            search_kwargs["call_counter"] = counter
        if agent_request is not None and "request" in inspect.signature(
            self.knowledge_service.search
        ).parameters:
            search_kwargs["request"] = agent_request
        result = await self.knowledge_service.search(
            issue.description,
            user,
            **search_kwargs,
        )
        if not self._knowledge_supports_counter:
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
        user: UserContext,
        correlation_id: str,
        lock: asyncio.Lock,
        ticket_created: dict,
        ticket_intent: TicketIntent,
        ticket_body: str | None = None,
        handoff_confirmed: bool = False,
        request_id: str | None = None,
        tenant_id: str | None = None,
        agent_request: AgentRequest | None = None,
        idempotency_key: str | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> IssueResult:
        if ticket_intent == TicketIntent.QUERY:
            return await self._query_tickets(issue, user, correlation_id)
        if ticket_intent != TicketIntent.CREATE:
            return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE")

        requester_id = user.entraObjectId or user.teamsUserId or ""
        if request_id:
            deduped = await self._deduped_ticket_result(
                issue=issue,
                request_id=request_id,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                ticket_service=self.ticket_service,
                requester_id=requester_id,
            )
            if deduped is not None:
                return deduped

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

        try:
            items = await self.ticket_service.get_ticket_items(correlation_id=correlation_id)
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        if handoff_confirmed:
            selected_item = handoff_ticket_item_fallback(items)
            selection_reason = "handoff_fallback" if selected_item else None
        else:
            selected_item = None
            selection_reason = None
        if selected_item is None:
            selection = await self.ticket_item_selector.select(
                items=items,
                issue_description=issue.description,
                execution_context=execution_context,
            )
            selected_item = selection.item
            selection_reason = selection.reason
        if selected_item is not None and selection_reason == "handoff_fallback":
            logger.info(
                "Handoff ticket creation used catalog fallback: item_id=%s "
                "correlation_id=%s",
                selected_item.id,
                correlation_id,
            )
        if selected_item is None:
            if selection_reason in {"model_unavailable", "model_error"}:
                question = (
                    "目前無法判定適用的派工單類別；已保留案件內容，"
                    "請稍後重試或聯絡線上客服。"
                )
            else:
                question = (
                    "目前無法從可用派工單類別判定最適合的一項；"
                    "請補充與目前案件最相關的系統、功能或錯誤訊息。"
                )
            return IssueResult(
                issueId=issue.id,
                resultType="NEED_MORE_INFO",
                questions=[question],
            )
        draft = TicketDraft(
            requesterId=requester_id,
            requesterName=user.displayName or "",
            requesterEmail=user.email or "",
            title=issue.description[:120],
            description=(ticket_body or issue.description),
            ticketItemId=selected_item.id,
        )
        try:
            ticket = await self.ticket_service.create_ticket(
                draft,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
        except TicketServiceDisabledError:
            return IssueResult(
                issueId=issue.id, resultType="FAILED", error="ticket_service_disabled"
            )
        except UntrustedRequesterError:
            return IssueResult(issueId=issue.id, resultType="FAILED", error="untrusted_requester")
        except (TicketServiceTimeout, TicketServiceError) as exc:
            return IssueResult(issueId=issue.id, resultType="FAILED", error=str(exc)[:300])

        if request_id and ticket.id:
            await self.ticket_request_dedupe.put(tenant_id, request_id, ticket.id)

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
