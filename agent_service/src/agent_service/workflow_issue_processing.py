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
        denied_issue_ids = self._issues_denied_by_llm_budget(state, it_issues)

        async def handle(issue: Issue) -> IssueResult:
            try:
                denied = self._budget_denied_result(issue, denied_issue_ids, correlation_id)
                if denied is not None:
                    return denied
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
        return {"issue_results": self._collect_issue_outcomes(it_issues, gathered, correlation_id)}

    @staticmethod
    def _budget_denied_result(
        issue: Issue,
        denied_issue_ids: set[int],
        correlation_id: str,
    ) -> IssueResult | None:
        if issue.id not in denied_issue_ids:
            return None
        from .observability import METRIC_LLM_BUDGET_DENIED, record_metric_counter

        record_metric_counter(
            METRIC_LLM_BUDGET_DENIED,
            attributes={"component": "knowledge_answer"},
        )
        logger.info(
            "agent_llm_budget_denied_total issue_id=%s correlation_id=%s",
            issue.id,
            correlation_id,
        )
        return IssueResult(
            issueId=issue.id,
            resultType="NO_KNOWLEDGE",
            terminalReason="LLM_BUDGET_EXCEEDED",
        )

    @staticmethod
    def _collect_issue_outcomes(
        it_issues: list[Issue],
        gathered: list[object],
        correlation_id: str,
    ) -> list[IssueResult]:
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
                issue_results.append(outcome)  # type: ignore[arg-type]
        return issue_results

    @staticmethod
    def _record_issue_budget_plan(
        execution_context: ExecutionContext,
        budget: object,
    ) -> None:
        issue_budgets = getattr(budget, "issue_budgets", ()) or ()
        for item in issue_budgets:
            mapping = (
                ("knowledge_answer", item.answer_slots),
                ("knowledge_relevance", item.relevance_slots),
                ("knowledge_rewrite", item.rewrite_slots),
                ("knowledge_answer_escalation", item.escalation_slots),
            )
            for component, slots in mapping:
                if slots:
                    execution_context.record_budget_event(
                        kind="planned",
                        component=component,
                        slots=slots,
                        issue_id=item.issue_id,
                    )
        for issue_id in getattr(budget, "unallocated_issue_ids", ()) or ():
            execution_context.record_budget_event(
                kind="denied",
                component="knowledge_answer",
                slots=1,
                issue_id=int(issue_id),
            )
        remaining = int(getattr(budget, "remaining_capacity", 0) or 0)
        if remaining > 0:
            execution_context.record_budget_event(
                kind="unused",
                component="request",
                slots=remaining,
            )

    def _issues_denied_by_llm_budget(
        self,
        state: AgentState,
        issues: list[Issue],
    ) -> set[int]:
        """Reserve answer slots before concurrent issue processing."""
        from .knowledge_pipeline.query_tier import classify_query_tier
        from .knowledge_pipeline.retrieval_state import RetrievalState
        from .llm_budget_plan import PlannedIssue, plan_request_llm_budget

        execution_context = state.get("execution_context")
        already_used = (
            int(execution_context.llm_calls.count) if execution_context is not None else 0
        )
        escalation_enabled = str(
            getattr(self.settings, "rag_answer_escalation_policy", "OFF") or "OFF"
        ).upper() not in {"", "OFF"}
        planned_issues: list[PlannedIssue] = []
        for issue in issues:
            if issue.route != "KNOWLEDGE" or issue.readiness != "READY":
                continue
            query = str(issue.retrieval_query or issue.description or "")
            provisional = classify_query_tier(
                RetrievalState(
                    raw_user_utterance=query,
                    resolved_issue_query=query,
                    search_query=query,
                ),
                min_score=float(getattr(self.settings, "min_score", 0.0) or 0.0),
                max_retrieval_rewrites=int(
                    getattr(self.settings, "max_retrieval_rewrites", 0) or 0
                ),
            )
            tier = str(provisional.tier.value)
            planned_issues.append(
                PlannedIssue(
                    issue_id=issue.id,
                    query_tier=tier if tier in {"trivial", "standard", "hard"} else "standard",
                    needs_answer=True,
                    allow_relevance=tier != "trivial",
                    allow_rewrite=tier == "hard"
                    and int(getattr(self.settings, "max_retrieval_rewrites", 0) or 0) > 0,
                    allow_escalation=escalation_enabled and tier == "hard",
                )
            )
        budget = plan_request_llm_budget(
            total_limit=int(self.settings.max_llm_calls_per_request),
            already_used=already_used,
            issues=tuple(planned_issues),
        )
        if execution_context is not None:
            self._record_issue_budget_plan(execution_context, budget)
        return set(budget.unallocated_issue_ids)

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
