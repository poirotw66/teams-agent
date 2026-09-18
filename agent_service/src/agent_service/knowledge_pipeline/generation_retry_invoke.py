"""Shared retry invoke helpers for grounded answer generation."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.security_policies import strip_unknown_policy_markers

from .grounding import (
    normalize_composite_citation_markers,
    remap_claim_marker_ids_to_chunk_ids,
    repair_structured_answer,
)
from .models import StructuredKnowledgeAnswer
from .prompts import ANSWER_PROMPT


def normalize_retry_response(
    response: StructuredKnowledgeAnswer,
    *,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
) -> tuple[StructuredKnowledgeAnswer, str]:
    repaired = repair_structured_answer(response)
    repaired.claims = remap_claim_marker_ids_to_chunk_ids(
        repaired.claims,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )
    answer = normalize_composite_citation_markers(repaired.answer.strip())
    return repaired, strip_unknown_policy_markers(answer)


async def invoke_structured_retry(
    host: Any,
    *,
    answer_model: BaseChatModel,
    question: str,
    context: str,
    human_content: str,
    component: str,
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
) -> tuple[StructuredKnowledgeAnswer, str]:
    async def _invoke() -> StructuredKnowledgeAnswer:
        return await answer_model.with_structured_output(
            StructuredKnowledgeAnswer
        ).ainvoke(
            [
                SystemMessage(
                    content=ANSWER_PROMPT.format(question=question, context=context)
                ),
                HumanMessage(content=human_content),
            ]
        )

    response = await host.invoke_llm(
        _invoke,
        component=component,
        execution_context=execution_context,
        counter=counter,
    )
    return normalize_retry_response(
        response,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )


__all__ = ["invoke_structured_retry", "normalize_retry_response"]
