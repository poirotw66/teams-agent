"""Workflow node implementations for the issue processing subgraph.

Public surface stays on ``IssueProcessingWorkflowMixin`` for graph wiring.
Knowledge, ticket, and retrieval-probe helpers live in sibling modules.
"""

from __future__ import annotations

import asyncio
import logging

from .confirmation import TicketIntent
from .contracts import AgentRequest, Issue, IssueResult, UserContext
from .execution_context import ExecutionContext
from .faq import citation_for_faq
from .knowledge import LlmCallCounter
from .workflow_helpers import AgentState
from .workflow_issue_knowledge_ops import IssueKnowledgeOps
from .workflow_issue_retrieval_probe import _retrieval_probe_is_answerable
from .workflow_issue_ticket_ops import IssueTicketOps

logger = logging.getLogger(__name__)

__all__ = ["IssueProcessingWorkflowMixin", "_retrieval_probe_is_answerable"]


class IssueProcessingWorkflowMixin(IssueKnowledgeOps, IssueTicketOps):
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

    async def _handle_faq_route(
        self,
        issue: Issue,
        *,
        user: UserContext,
        correlation_id: str,
        counter: LlmCallCounter,
        lock: asyncio.Lock,
        agent_request: AgentRequest | None,
        execution_context: ExecutionContext | None,
    ) -> IssueResult:
        entry = (
            await asyncio.to_thread(
                self.faq_service.get,
                issue.faqKey,
                tuple(user.groups),
            )
            if issue.faqKey
            else None
        )
        if entry is not None:
            # Spec §7.3: FAQ answer used VERBATIM. No LLM, no rewriting.
            # Attach FAQ id/version as a citation so Judge can verify provenance.
            return IssueResult(
                issueId=issue.id,
                resultType="FAQ_ANSWERED",
                answer=entry.answer,
                sources=[citation_for_faq(entry, include_evidence=True)],
                backend="FAQ",
                faqId=entry.id,
                faqKey=entry.faqKey,
                faqVersionId=entry.versionId,
            )
        # Miss or disabled entry falls back to KNOWLEDGE, never fails.
        return await self._handle_knowledge(
            issue,
            user,
            correlation_id,
            counter,
            lock,
            agent_request=agent_request,
            execution_context=execution_context,
        )

    async def _probe_need_more_info(
        self,
        issue: Issue,
        *,
        user: UserContext,
        correlation_id: str,
        counter: LlmCallCounter,
        lock: asyncio.Lock,
        agent_request: AgentRequest | None,
        execution_context: ExecutionContext | None,
    ) -> IssueResult:
        probe = await self._handle_knowledge(
            issue,
            user,
            correlation_id,
            counter,
            lock,
            agent_request=agent_request,
            execution_context=execution_context,
        )
        if _retrieval_probe_is_answerable(issue, probe):
            return probe
        return IssueResult(
            issueId=issue.id,
            resultType="NEED_MORE_INFO",
            questions=issue.missingInfo,
            backend=probe.backend,
            terminalReason="CLARIFICATION_REQUIRED",
            retrievalTrace=probe.retrievalTrace,
        )

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
            return await self._probe_need_more_info(
                issue,
                user=user,
                correlation_id=correlation_id,
                counter=counter,
                lock=lock,
                agent_request=agent_request,
                execution_context=execution_context,
            )

        if issue.route == "FAQ":
            return await self._handle_faq_route(
                issue,
                user=user,
                correlation_id=correlation_id,
                counter=counter,
                lock=lock,
                agent_request=agent_request,
                execution_context=execution_context,
            )

        if issue.route == "KNOWLEDGE":
            return await self._handle_knowledge(
                issue,
                user,
                correlation_id,
                counter,
                lock,
                agent_request=agent_request,
                execution_context=execution_context,
            )

        if issue.route == "TICKET":
            # Defense in depth: extractor routes are advisory.  A message
            # with no deterministic ticket intent must not call Ticket API.
            return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE")

        # Defensive fallback: NOT_IT issues are filtered out before this
        # point (Filter IT Issues node), so this should be unreachable.
        return IssueResult(issueId=issue.id, resultType="FAILED", error="unexpected_route")
