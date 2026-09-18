"""Top-level search loop for HybridKnowledgeService (stage orchestration)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from langchain_core.language_models import BaseChatModel

from agent_service.contracts import (
    EVALUATION_EVIDENCE_CHANNEL,
    AgentRequest,
    KnowledgeResult,
    UserContext,
)
from agent_service.execution_context import (
    ExecutionContext,
    RequestDeadlineExceeded,
    RequestModelBudgetExceeded,
    RequestOperationTimedOut,
)
from agent_service.llm_call_counter import LlmCallCounter

from .planner import bounded_facet_queries, missing_diagnosis_facet_queries
from .retrieval_state import RetrievalState

_KNOWLEDGE_REWRITE_PATH_SLOTS = 3


def resolve_llm_counter(
    execution_context: ExecutionContext | None,
    call_counter: LlmCallCounter | None,
) -> LlmCallCounter:
    if execution_context is not None:
        return execution_context.llm_calls
    return call_counter or LlmCallCounter()


async def prepare_retrieval_state(
    *,
    query: str,
    raw_user_utterance: str,
    groups: set[str],
    retrieve: Callable[..., Awaitable[RetrievalState]],
) -> RetrievalState:
    from dataclasses import replace

    facet_queries = bounded_facet_queries(query)
    if not facet_queries and raw_user_utterance and raw_user_utterance != query:
        facet_queries = bounded_facet_queries(raw_user_utterance)
    state = RetrievalState(
        raw_user_utterance=raw_user_utterance,
        resolved_issue_query=query,
        search_query=query,
        facet_queries=facet_queries,
    )
    retrieve_started = time.perf_counter()
    state = await retrieve(state, groups)
    gap_queries = missing_diagnosis_facet_queries(
        state.resolved_issue_query,
        "\n".join(
            f"{result.chunk.title}\n{result.chunk.content}" for result in state.results
        ),
    )
    if gap_queries:
        state = await retrieve(replace(state, facet_queries=gap_queries), groups)
    state.stage_timings_ms["retrievalMs"] = round(
        (time.perf_counter() - retrieve_started) * 1000, 1
    )
    return state


async def generate_if_relevant(
    *,
    state: RetrievalState,
    counter: LlmCallCounter,
    model: BaseChatModel | None,
    execution_context: ExecutionContext | None,
    include_retrieval_evidence: bool,
    total_started: float,
    documents_are_relevant: Callable[..., Awaitable[bool]],
    generate: Callable[..., Awaitable[KnowledgeResult]],
    with_trace: Callable[..., KnowledgeResult],
) -> KnowledgeResult | None:
    relevance_started = time.perf_counter()
    is_relevant = await documents_are_relevant(
        state, counter, execution_context=execution_context, model=model
    )
    state.stage_timings_ms["relevanceMs"] = round(
        state.stage_timings_ms.get("relevanceMs", 0.0)
        + (time.perf_counter() - relevance_started) * 1000,
        1,
    )
    if not is_relevant:
        return None
    generate_started = time.perf_counter()
    result = await generate(
        state,
        counter,
        execution_context=execution_context,
        model=model,
        include_retrieval_evidence=include_retrieval_evidence,
    )
    state.stage_timings_ms["generateMs"] = round(
        (time.perf_counter() - generate_started) * 1000, 1
    )
    state.stage_timings_ms["totalMs"] = round(
        (time.perf_counter() - total_started) * 1000, 1
    )
    fallback_path = "GENERATED_ANSWER" if result.found else "SAFE_NO_ANSWER"
    return with_trace(
        result,
        state,
        execution_context=execution_context,
        fallback_path=fallback_path,
        terminal_reason=None if result.found else "UNGROUNDED_ANSWER",
    )


async def rewrite_or_budget_limit(
    *,
    state: RetrievalState,
    counter: LlmCallCounter,
    model: BaseChatModel,
    execution_context: ExecutionContext | None,
    groups: set[str],
    rewrite: Callable[..., Awaitable[RetrievalState]],
    retrieve: Callable[..., Awaitable[RetrievalState]],
    with_trace: Callable[..., KnowledgeResult],
    limit_result: Callable[[str], KnowledgeResult],
) -> tuple[KnowledgeResult | None, RetrievalState]:
    if execution_context is not None:
        try:
            execution_context.ensure_budget_slots(_KNOWLEDGE_REWRITE_PATH_SLOTS)
        except RequestModelBudgetExceeded:
            return (
                with_trace(
                    limit_result("BUDGET_EXCEEDED"),
                    state,
                    execution_context=execution_context,
                    fallback_path="BUDGET_LIMIT",
                    terminal_reason="BUDGET_EXCEEDED",
                ),
                state,
            )
    state = await rewrite(
        state, counter, execution_context=execution_context, model=model
    )
    state = await retrieve(state, groups)
    return None, state


def limit_trace(
    *,
    reason: str,
    fallback_path: str,
    state: RetrievalState,
    execution_context: ExecutionContext | None,
    with_trace: Callable[..., KnowledgeResult],
    limit_result: Callable[[str], KnowledgeResult],
) -> KnowledgeResult:
    return with_trace(
        limit_result(reason),
        state,
        execution_context=execution_context,
        fallback_path=fallback_path,
        terminal_reason=reason,
    )


async def iterate_relevance_rewrites(
    *,
    state: RetrievalState,
    counter: LlmCallCounter,
    model: BaseChatModel | None,
    execution_context: ExecutionContext | None,
    include_retrieval_evidence: bool,
    total_started: float,
    groups: set[str],
    max_retrieval_rewrites: int,
    documents_are_relevant: Callable[..., Awaitable[bool]],
    generate: Callable[..., Awaitable[KnowledgeResult]],
    rewrite: Callable[..., Awaitable[RetrievalState]],
    retrieve: Callable[..., Awaitable[RetrievalState]],
    with_trace: Callable[..., KnowledgeResult],
    limit_result: Callable[[str], KnowledgeResult],
) -> KnowledgeResult | None:
    """Run relevance/generate/rewrite until answer or exhaustion. None = no hit."""
    while True:
        traced = await generate_if_relevant(
            state=state,
            counter=counter,
            model=model,
            execution_context=execution_context,
            include_retrieval_evidence=include_retrieval_evidence,
            total_started=total_started,
            documents_are_relevant=documents_are_relevant,
            generate=generate,
            with_trace=with_trace,
        )
        if traced is not None:
            return traced
        if not (state.attempt < max_retrieval_rewrites and model):
            return None
        early, state = await rewrite_or_budget_limit(
            state=state,
            counter=counter,
            model=model,
            execution_context=execution_context,
            groups=groups,
            rewrite=rewrite,
            retrieve=retrieve,
            with_trace=with_trace,
            limit_result=limit_result,
        )
        if early is not None:
            return early


async def run_search_with_limits(
    *,
    state: RetrievalState,
    counter: LlmCallCounter,
    model: BaseChatModel | None,
    execution_context: ExecutionContext | None,
    include_retrieval_evidence: bool,
    total_started: float,
    groups: set[str],
    max_retrieval_rewrites: int,
    documents_are_relevant: Callable[..., Awaitable[bool]],
    generate: Callable[..., Awaitable[KnowledgeResult]],
    rewrite: Callable[..., Awaitable[RetrievalState]],
    retrieve: Callable[..., Awaitable[RetrievalState]],
    with_trace: Callable[..., KnowledgeResult],
    limit_result: Callable[[str], KnowledgeResult],
    set_llm_count: Callable[[int], None],
) -> KnowledgeResult | None:
    """Iterate rewrites; return hit or limit result. None = exhausted evidence."""
    try:
        traced = await iterate_relevance_rewrites(
            state=state,
            counter=counter,
            model=model,
            execution_context=execution_context,
            include_retrieval_evidence=include_retrieval_evidence,
            total_started=total_started,
            groups=groups,
            max_retrieval_rewrites=max_retrieval_rewrites,
            documents_are_relevant=documents_are_relevant,
            generate=generate,
            rewrite=rewrite,
            retrieve=retrieve,
            with_trace=with_trace,
            limit_result=limit_result,
        )
        if traced is not None:
            set_llm_count(counter.count)
            return traced
    except RequestModelBudgetExceeded:
        set_llm_count(counter.count)
        return limit_trace(
            reason="BUDGET_EXCEEDED",
            fallback_path="BUDGET_LIMIT",
            state=state,
            execution_context=execution_context,
            with_trace=with_trace,
            limit_result=limit_result,
        )
    except (RequestDeadlineExceeded, RequestOperationTimedOut):
        set_llm_count(counter.count)
        return limit_trace(
            reason="DEADLINE_EXCEEDED",
            fallback_path="DEADLINE_LIMIT",
            state=state,
            execution_context=execution_context,
            with_trace=with_trace,
            limit_result=limit_result,
        )
    return None


async def run_search_loop(
    *,
    query: str,
    user_context: UserContext,
    call_counter: LlmCallCounter | None,
    execution_context: ExecutionContext | None,
    answer_model: BaseChatModel | None,
    request: AgentRequest | None,
    default_model: BaseChatModel | None,
    max_retrieval_rewrites: int,
    retrieve: Callable[..., Awaitable[RetrievalState]],
    documents_are_relevant: Callable[..., Awaitable[bool]],
    generate: Callable[..., Awaitable[KnowledgeResult]],
    rewrite: Callable[..., Awaitable[RetrievalState]],
    with_trace: Callable[..., KnowledgeResult],
    limit_result: Callable[[str], KnowledgeResult],
    no_answer: Callable[[], KnowledgeResult],
    set_llm_count: Callable[[int], None],
) -> KnowledgeResult:
    counter = resolve_llm_counter(execution_context, call_counter)
    groups = set(user_context.groups)
    model = default_model if answer_model is None else answer_model
    include_evidence = (
        request is not None and request.channel == EVALUATION_EVIDENCE_CHANNEL
    )
    raw_utterance = request.message.text if request is not None else query
    total_started = time.perf_counter()
    state = await prepare_retrieval_state(
        query=query,
        raw_user_utterance=raw_utterance,
        groups=groups,
        retrieve=retrieve,
    )
    hit = await run_search_with_limits(
        state=state,
        counter=counter,
        model=model,
        execution_context=execution_context,
        include_retrieval_evidence=include_evidence,
        total_started=total_started,
        groups=groups,
        max_retrieval_rewrites=max_retrieval_rewrites,
        documents_are_relevant=documents_are_relevant,
        generate=generate,
        rewrite=rewrite,
        retrieve=retrieve,
        with_trace=with_trace,
        limit_result=limit_result,
        set_llm_count=set_llm_count,
    )
    if hit is not None:
        return hit
    set_llm_count(counter.count)
    return with_trace(
        no_answer(),
        state,
        execution_context=execution_context,
        fallback_path="NO_RELEVANT_EVIDENCE",
        terminal_reason="NO_RELEVANT_EVIDENCE",
    )


__all__ = [
    "generate_if_relevant",
    "prepare_retrieval_state",
    "resolve_llm_counter",
    "run_search_loop",
]
