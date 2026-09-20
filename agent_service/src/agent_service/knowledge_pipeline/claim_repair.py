"""LLM claim-repair helper for grounded answer generation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from agent_service.contracts import GroundedClaim
from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult
from agent_service.structured_invoke import ainvoke_structured

from .models import GroundedClaimRepair
from .prompts import CLAIM_REPAIR_PROMPT


async def repair_claims_with_model(
    model: BaseChatModel,
    *,
    answer: str,
    results: list[SearchResult],
    counter: LlmCallCounter,
    invoke_llm: Callable[..., Awaitable[Any]],
    execution_context: ExecutionContext | None = None,
) -> list[GroundedClaim]:
    context = "\n\n".join(
        f"[{result.chunk.chunk_id}] {result.chunk.title}\n{result.chunk.content}"
        for result in results
    )

    async def _invoke_repair() -> GroundedClaimRepair:
        return await ainvoke_structured(
            model,
            GroundedClaimRepair,
            [
                SystemMessage(
                    content=CLAIM_REPAIR_PROMPT.format(
                        answer=answer,
                        context=context,
                    )
                ),
                HumanMessage(content="請提取並校準事實主張（claims）。"),
            ],
        )

    try:
        repair_output = await invoke_llm(
            _invoke_repair,
            component="knowledge_repair_claims",
            execution_context=execution_context,
            counter=counter,
        )
        return repair_output.claims
    except Exception:
        return []


__all__ = ["repair_claims_with_model"]
