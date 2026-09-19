"""Knowledge-route helpers for the issue processing subgraph."""

from __future__ import annotations

import asyncio
import inspect
import logging

from .contracts import AgentRequest, Issue, IssueResult, UserContext
from .execution_context import ExecutionContext, RequestDeadlineExceeded
from .extractor import HUMAN_ESCALATION_ISSUE_DESCRIPTION
from .issue_trust import issue_retrieval_text
from .knowledge import LlmCallCounter

logger = logging.getLogger(__name__)


class IssueKnowledgeOps:
    """FAQ/knowledge search nodes shared by issue processing."""

    def _governed_answer_model(self) -> object | None:
        runtime = getattr(self, "governance_runtime", None)
        resolve = getattr(runtime, "resolve_model", None)
        cache = getattr(runtime, "chat_model_for", None)
        if resolve is None or cache is None:
            return None
        try:
            resolved = resolve(config_id="rag-answer-model")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Answer model lookup failed (%s); using startup model",
                type(exc).__name__,
            )
            return None
        try:
            return cache(resolved)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Answer model build failed (%s); using startup model",
                type(exc).__name__,
            )
            return None

    async def _knowledge_budget_or_deadline_result(
        self,
        issue: Issue,
        *,
        correlation_id: str,
        counter: LlmCallCounter,
        lock: asyncio.Lock,
        execution_context: ExecutionContext | None,
    ) -> IssueResult | None:
        async with lock:
            deadline_exceeded = False
            if execution_context is not None:
                try:
                    execution_context.ensure_deadline()
                except RequestDeadlineExceeded:
                    deadline_exceeded = True
                budget_exceeded = execution_context.budget_remaining() <= 0
            else:
                budget_exceeded = counter.count >= self.settings.max_llm_calls_per_request

        if not budget_exceeded and not deadline_exceeded:
            return None

        # Spec §16: stop making further LLM calls and degrade gracefully
        # rather than raising.
        backend = "DEADLINE_EXCEEDED" if deadline_exceeded else "BUDGET_EXCEEDED"
        logger.warning(
            "LLM guard tripped, degrading issue to NO_KNOWLEDGE: "
            "issue_id=%s backend=%s correlation_id=%s",
            issue.id,
            backend,
            correlation_id,
        )
        return IssueResult(issueId=issue.id, resultType="NO_KNOWLEDGE", backend=backend)

    def _knowledge_search_kwargs(
        self,
        *,
        correlation_id: str,
        counter: LlmCallCounter,
        agent_request: AgentRequest | None,
        execution_context: ExecutionContext | None,
    ) -> dict[str, object]:
        search_kwargs: dict[str, object] = {"correlation_id": correlation_id}
        if self._knowledge_supports_counter:
            search_kwargs["call_counter"] = counter
        search_params = inspect.signature(self.knowledge_service.search).parameters
        if execution_context is not None and "execution_context" in search_params:
            search_kwargs["execution_context"] = execution_context
        if agent_request is not None and "request" in search_params:
            search_kwargs["request"] = agent_request
        answer_model = self._governed_answer_model()
        if answer_model is not None and "answer_model" in search_params:
            search_kwargs["answer_model"] = answer_model
        return search_kwargs

    async def _handle_knowledge(
        self,
        issue: Issue,
        user: UserContext,
        correlation_id: str,
        counter: LlmCallCounter,
        lock: asyncio.Lock,
        *,
        agent_request: AgentRequest | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> IssueResult:
        if issue.description == HUMAN_ESCALATION_ISSUE_DESCRIPTION:
            return IssueResult(
                issueId=issue.id,
                resultType="NO_KNOWLEDGE",
                backend="ESCALATION",
            )

        guarded = await self._knowledge_budget_or_deadline_result(
            issue,
            correlation_id=correlation_id,
            counter=counter,
            lock=lock,
            execution_context=execution_context,
        )
        if guarded is not None:
            return guarded

        search_kwargs = self._knowledge_search_kwargs(
            correlation_id=correlation_id,
            counter=counter,
            agent_request=agent_request,
            execution_context=execution_context,
        )
        user_utterance = ""
        if agent_request is not None and getattr(agent_request, "message", None) is not None:
            user_utterance = getattr(agent_request.message, "text", "") or ""
        result = await self.knowledge_service.search(
            issue_retrieval_text(issue, user_utterance=user_utterance),
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
                terminalReason=result.terminalReason,
                retrievalTrace=result.retrievalTrace,
                answerability=result.answerability,
                claims=result.claims,
                policyAdvisories=result.policyAdvisories,
                unknowns=result.unknowns,
            )
        return IssueResult(
            issueId=issue.id,
            resultType="NO_KNOWLEDGE",
            backend=result.backend,
            terminalReason=result.terminalReason,
            retrievalTrace=result.retrievalTrace,
        )
