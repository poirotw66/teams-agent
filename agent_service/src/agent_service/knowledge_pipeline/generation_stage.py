"""Grounded answer generation stage extracted from HybridKnowledgeService.

I/O (LLM invoke, claim repair, citation URL build) is provided via callbacks
so this module stays free of HybridIndex / settings coupling.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel

from agent_service.contracts import Citation, GroundedClaim, KnowledgeResult
from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult

from .citation_assembly import build_chunk_document_maps
from .generation_stage_invoke import (
    build_context_and_markers,
    invoke_initial_grounded_answer,
    resolve_cited_document_keys,
)
from .generation_stage_result import (
    align_claims_with_citations,
    assemble_grounded_knowledge_result,
)


class GenerationHost(Protocol):
    """Callbacks HybridKnowledgeService supplies to the generation stage."""

    async def invoke_llm(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        component: str,
        execution_context: ExecutionContext | None,
        counter: LlmCallCounter,
    ) -> Any: ...

    def document_key(self, result: SearchResult) -> str: ...

    def citation_for(
        self,
        result: SearchResult,
        *,
        evidence_results: list[SearchResult] | None = None,
    ) -> Citation: ...

    def images_for(self, cited_results: list[SearchResult]) -> list: ...

    @property
    def chunk_by_id(self) -> dict[str, Any]: ...

    def deterministic_grounded_answer(
        self,
        results: list[SearchResult],
        *,
        include_retrieval_evidence: bool,
    ) -> KnowledgeResult: ...

    def no_answer(self) -> KnowledgeResult: ...

    def evaluate_retrieval_confidence(self, state: Any) -> tuple[str, Any]: ...

    async def repair_claims_with_model(
        self,
        model: BaseChatModel,
        *,
        answer: str,
        results: list[SearchResult],
        counter: LlmCallCounter,
        execution_context: ExecutionContext | None = None,
    ) -> list[GroundedClaim]: ...


async def generate_grounded_answer(
    host: GenerationHost,
    state: Any,
    counter: LlmCallCounter,
    *,
    execution_context: ExecutionContext | None = None,
    model: BaseChatModel | None = None,
    include_retrieval_evidence: bool,
) -> KnowledgeResult:
    results = state.results
    answer_model = model
    if not results:
        return host.no_answer()

    unique_doc_keys, chunk_to_doc_idx, _document_by_chunk_id = build_chunk_document_maps(
        results,
        document_key=host.document_key,
    )

    if not answer_model:
        return host.deterministic_grounded_answer(
            results,
            include_retrieval_evidence=include_retrieval_evidence,
        )

    context, marker_to_chunk_ids, chunk_content_by_id, bundles = build_context_and_markers(
        results,
        chunk_to_doc_idx,
        chunk_by_id=getattr(host, "chunk_by_id", None) or None,
    )
    response, answer = await invoke_initial_grounded_answer(
        host,
        state=state,
        results=results,
        answer_model=answer_model,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        counter=counter,
        execution_context=execution_context,
    )
    cited = resolve_cited_document_keys(
        host=host,
        response=response,
        answer=answer,
        results=results,
        unique_doc_keys=unique_doc_keys,
        chunk_to_doc_idx=chunk_to_doc_idx,
        bundles=bundles,
    )
    if isinstance(cited, KnowledgeResult):
        return cited
    answer, ordered_cited_doc_keys = cited

    aligned = await align_claims_with_citations(
        host,
        response=response,
        answer=answer,
        results=results,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        answer_model=answer_model,
        counter=counter,
        execution_context=execution_context,
        bundles=bundles,
    )
    if isinstance(aligned, KnowledgeResult):
        return aligned
    response, common_doc_keys = aligned

    return assemble_grounded_knowledge_result(
        host,
        response=response,
        answer=answer,
        results=results,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        common_doc_keys=common_doc_keys,
        unique_doc_keys=unique_doc_keys,
        chunk_to_doc_idx=chunk_to_doc_idx,
        include_retrieval_evidence=include_retrieval_evidence,
    )


__all__ = ["GenerationHost", "generate_grounded_answer"]
