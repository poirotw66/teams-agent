"""Generation-host adapter for HybridKnowledgeService."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel

from agent_service.contracts import AgentImage, Citation, GroundedClaim, KnowledgeResult
from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult

if TYPE_CHECKING:
    from agent_service.knowledge_hybrid import HybridKnowledgeService, _RetrievalState

class _HybridGenerationHost:
    """Adapts HybridKnowledgeService private helpers to GenerationHost."""

    def __init__(self, service: HybridKnowledgeService) -> None:
        self._service = service

    async def invoke_llm(
        self,
        factory: Callable[[], Awaitable[object]],
        *,
        component: str,
        execution_context: ExecutionContext | None,
        counter: LlmCallCounter,
    ) -> object:
        return await self._service._invoke_llm(
            factory,
            component=component,
            execution_context=execution_context,
            counter=counter,
        )

    def document_key(self, result: SearchResult) -> str:
        return self._service._document_key(result)

    def citation_for(
        self,
        result: SearchResult,
        *,
        evidence_results: list[SearchResult] | None = None,
    ) -> Citation:
        return self._service._citation_for(
            result, evidence_results=evidence_results
        )

    def images_for(self, cited_results: list[SearchResult]) -> list[AgentImage]:
        return self._service._images_for(cited_results)

    def deterministic_grounded_answer(
        self,
        results: list[SearchResult],
        *,
        include_retrieval_evidence: bool,
    ) -> KnowledgeResult:
        return self._service._deterministic_grounded_answer(
            results,
            include_retrieval_evidence=include_retrieval_evidence,
        )

    def no_answer(self) -> KnowledgeResult:
        return self._service._no_answer()

    def evaluate_retrieval_confidence(
        self, state: _RetrievalState
    ) -> tuple[str, object]:
        return self._service._evaluate_retrieval_confidence(state)

    async def repair_claims_with_model(
        self,
        model: BaseChatModel,
        *,
        answer: str,
        results: list[SearchResult],
        counter: LlmCallCounter,
        execution_context: ExecutionContext | None = None,
    ) -> list[GroundedClaim]:
        return await self._service._repair_claims_with_model(
            model,
            answer=answer,
            results=results,
            counter=counter,
            execution_context=execution_context,
        )


__all__ = ["_HybridGenerationHost"]
