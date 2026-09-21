"""Relevance grading and query-rewrite stages for HybridKnowledgeService."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.rag_observability import (
    record_relevance_deterministic_skip,
    record_relevance_llm_outcome,
)
from agent_service.structured_invoke import ainvoke_structured

from .models import RelevanceDecision, RewrittenQuery
from .prompts import REWRITE_PROMPT
from .relevance import (
    annotate_relevance_attempts,
    build_relevance_grade_context,
    deterministic_relevance_without_model,
    evaluate_retrieval_confidence,
    format_grade_prompt,
)

_REWRITE_CONSTRAINT_MARKERS: tuple[str, ...] = (
    "未確認政策",
    "政策未確認",
    "來源能支持哪些答案",
    "來源能支持",
    "為何不能",
    "不能",
    "不可",
    "不得",
    "可否",
    "能否",
    "是否可以",
    "避免",
    "限制",
    "不應",
    "為何",
    "處置原則",
    "操作順序",
    "五檔",
)


def _annotate_and_skip(state: Any, *, decision: str, is_relevant: bool) -> bool:
    annotate_relevance_attempts(
        state.trace_attempts,
        decision=decision,
        is_relevant=is_relevant,
    )
    if is_relevant or decision == "DETERMINISTIC_RELEVANCE":
        record_relevance_deterministic_skip()
    return is_relevant


def _try_deterministic_relevance_short_circuit(
    state: Any,
    *,
    decision_label: str,
    is_deterministic: bool,
    skip_relevance_llm_on_high_confidence: bool,
    answer_model: BaseChatModel | None,
) -> bool | None:
    """Return a relevance bool when LLM can be skipped; otherwise None."""
    if decision_label in ("BELOW_MIN_SCORE", "LOW_CONFIDENCE_FAIL"):
        annotate_relevance_attempts(
            state.trace_attempts,
            decision=decision_label,
            is_relevant=False,
        )
        return False

    if decision_label == "HIGH_CONFIDENCE_PASS" and skip_relevance_llm_on_high_confidence:
        return _annotate_and_skip(
            state, decision="HIGH_CONFIDENCE_PASS", is_relevant=True
        )

    query_tier = str(getattr(state, "query_tier", "") or "").strip().lower()
    if query_tier == "trivial":
        return _annotate_and_skip(state, decision="TRIVIAL_TIER_SKIP", is_relevant=True)

    if not answer_model:
        is_relevant = deterministic_relevance_without_model(
            query=state.resolved_issue_query,
            results=state.results,
            is_deterministic=is_deterministic,
        )
        return _annotate_and_skip(
            state, decision="DETERMINISTIC_RELEVANCE", is_relevant=is_relevant
        )
    return None


async def _grade_relevance_with_llm(
    state: Any,
    *,
    is_deterministic: bool,
    answer_model: BaseChatModel,
    invoke_llm: Callable[..., Awaitable[Any]],
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> bool:
    context = build_relevance_grade_context(state.results)
    deterministic_relevant = deterministic_relevance_without_model(
        query=state.resolved_issue_query,
        results=state.results,
        is_deterministic=is_deterministic,
    )

    async def _grade() -> RelevanceDecision:
        return await ainvoke_structured(
            answer_model,
            RelevanceDecision,
            [
                HumanMessage(
                    content=format_grade_prompt(
                        question=state.resolved_issue_query,
                        context=context,
                    )
                )
            ],
        )

    decision = await invoke_llm(
        _grade,
        component="knowledge_relevance",
        execution_context=execution_context,
        counter=counter,
    )
    annotate_relevance_attempts(
        state.trace_attempts,
        decision="LLM_RELEVANCE",
        is_relevant=decision.relevant,
    )
    record_relevance_llm_outcome(
        deterministic_relevant=deterministic_relevant,
        llm_relevant=bool(decision.relevant),
    )
    return decision.relevant


async def documents_are_relevant(
    state: Any,
    *,
    min_score: float,
    skip_relevance_llm_on_high_confidence: bool,
    answer_model: BaseChatModel | None,
    invoke_llm: Callable[..., Awaitable[Any]],
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> bool:
    decision_label, is_deterministic = evaluate_retrieval_confidence(
        query=state.resolved_issue_query,
        results=state.results,
        min_score=min_score,
        filter_displaced_top1=state.filter_displaced_top1,
    )
    short_circuit = _try_deterministic_relevance_short_circuit(
        state,
        decision_label=decision_label,
        is_deterministic=is_deterministic,
        skip_relevance_llm_on_high_confidence=skip_relevance_llm_on_high_confidence,
        answer_model=answer_model,
    )
    if short_circuit is not None:
        return short_circuit
    if answer_model is None:
        return False
    return await _grade_relevance_with_llm(
        state,
        is_deterministic=is_deterministic,
        answer_model=answer_model,
        invoke_llm=invoke_llm,
        counter=counter,
        execution_context=execution_context,
    )


def preserve_rewrite_constraints(
    *,
    rewritten: str,
    resolved_issue_query: str,
    raw_user_utterance: str | None,
) -> str:
    source_texts = [resolved_issue_query]
    if raw_user_utterance:
        source_texts.append(raw_user_utterance)

    missing_to_prepend: list[str] = []
    for marker in _REWRITE_CONSTRAINT_MARKERS:
        if (
            any(marker in src for src in source_texts)
            and marker not in rewritten
            and not any(marker in existing for existing in missing_to_prepend)
            and not any(existing in marker for existing in missing_to_prepend)
        ):
            missing_to_prepend.append(marker)
    if missing_to_prepend:
        return f"{' '.join(missing_to_prepend)} {rewritten}".strip()
    return rewritten


async def rewrite_search_query(
    state: Any,
    *,
    answer_model: BaseChatModel,
    invoke_llm: Callable[..., Awaitable[Any]],
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
    state_factory: Callable[..., Any],
) -> Any:
    async def _invoke_rewrite() -> RewrittenQuery:
        return await ainvoke_structured(
            answer_model,
            RewrittenQuery,
            [
                HumanMessage(
                    content=REWRITE_PROMPT.format(
                        question=state.resolved_issue_query,
                    )
                )
            ],
        )

    decision = await invoke_llm(
        _invoke_rewrite,
        component="knowledge_rewrite",
        execution_context=execution_context,
        counter=counter,
    )
    rewritten = preserve_rewrite_constraints(
        rewritten=decision.query.strip(),
        resolved_issue_query=state.resolved_issue_query,
        raw_user_utterance=state.raw_user_utterance,
    )

    for attempt in state.trace_attempts:
        if attempt.rewriteQuery is None and attempt.isRelevant is False:
            attempt.rewriteQuery = rewritten
    return state_factory(
        raw_user_utterance=state.raw_user_utterance,
        resolved_issue_query=state.resolved_issue_query,
        search_query=rewritten,
        facet_queries=state.facet_queries,
        results=state.results,
        raw_results=getattr(state, "raw_results", []) or [],
        filter_displaced_top1=getattr(state, "filter_displaced_top1", False),
        trace_attempts=state.trace_attempts,
        attempt=state.attempt + 1,
        stage_timings_ms=state.stage_timings_ms,
        query_tier=getattr(state, "query_tier", None),
        enable_generation_retries=getattr(state, "enable_generation_retries", True),
        candidate_chunk_ids=getattr(state, "candidate_chunk_ids", ()),
        generator_context_chunk_ids=getattr(state, "generator_context_chunk_ids", ()),
    )


__all__ = [
    "documents_are_relevant",
    "preserve_rewrite_constraints",
    "rewrite_search_query",
]
