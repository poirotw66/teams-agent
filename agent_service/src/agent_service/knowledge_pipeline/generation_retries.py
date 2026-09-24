"""Retry loops for grounded answer generation (coverage / false-NONE)."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel

from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult

from .generation_retry_strategies import (
    maybe_retry_error_coverage,
    maybe_retry_false_none,
    maybe_retry_procedure_coverage,
    maybe_retry_ticket_intake_coverage,
    maybe_retry_visual_evidence,
)
from .models import StructuredKnowledgeAnswer


async def apply_generation_retries(
    host: Any,
    *,
    state: Any,
    results: list[SearchResult],
    answer_model: BaseChatModel,
    context: str,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
    response: StructuredKnowledgeAnswer,
    answer: str,
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
    enable_generation_retries: bool = True,
) -> tuple[StructuredKnowledgeAnswer, str]:
    if not enable_generation_retries:
        return response, answer
    response, answer = await maybe_retry_false_none(
        host,
        state=state,
        results=results,
        answer_model=answer_model,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        response=response,
        answer=answer,
        counter=counter,
        execution_context=execution_context,
    )
    response, answer = await maybe_retry_error_coverage(
        host,
        state=state,
        answer_model=answer_model,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        response=response,
        answer=answer,
        counter=counter,
        execution_context=execution_context,
    )
    response, answer = await maybe_retry_procedure_coverage(
        host,
        state=state,
        answer_model=answer_model,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        response=response,
        answer=answer,
        counter=counter,
        execution_context=execution_context,
    )
    response, answer = await maybe_retry_ticket_intake_coverage(
        host,
        state=state,
        answer_model=answer_model,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        response=response,
        answer=answer,
        counter=counter,
        execution_context=execution_context,
    )
    return await maybe_retry_visual_evidence(
        host,
        state=state,
        answer_model=answer_model,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        response=response,
        answer=answer,
        counter=counter,
        execution_context=execution_context,
    )


__all__ = ["apply_generation_retries"]
