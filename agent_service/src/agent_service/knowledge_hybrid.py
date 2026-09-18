"""HybridKnowledgeService adapter: wraps HybridIndex via pipeline stages."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from langchain_core.language_models import BaseChatModel

from .contracts import (
    AgentImage,
    AgentRequest,
    Citation,
    GroundedClaim,
    KnowledgeResult,
    UserContext,
)
from .execution_context import ExecutionContext
from .knowledge_pipeline import (
    StructuredKnowledgeAnswer,
    answer_passes_safety_checks,
    filter_cross_scenario_chunks,
    prune_unbacked_sentences_and_citations,
    prune_uncited_material_sentences,
    repair_structured_answer,
    sanitize_answer_security,
    structured_answer_is_grounded,
)
from .knowledge_pipeline.citation_io import (
    build_citation,
    images_for_cited_results,
    retrieval_evidence,
    unique_citations,
)
from .knowledge_pipeline.citation_io import (
    deterministic_grounded_answer as build_deterministic_grounded_answer,
)
from .knowledge_pipeline.citation_io import (
    document_key as citation_document_key,
)
from .knowledge_pipeline.claim_repair import repair_claims_with_model
from .knowledge_pipeline.document_selection import (
    canonical_version_results,
    inject_enterprise_app_evidence,
    select_document_chunks,
)
from .knowledge_pipeline.generation_host import _HybridGenerationHost
from .knowledge_pipeline.generation_stage import generate_grounded_answer
from .knowledge_pipeline.relevance import evaluate_retrieval_confidence
from .knowledge_pipeline.relevance_stage import (
    documents_are_relevant as grade_documents_are_relevant,
)
from .knowledge_pipeline.relevance_stage import (
    rewrite_search_query,
)
from .knowledge_pipeline.retrieval_stage import RetrievalHost, run_retrieve
from .knowledge_pipeline.retrieval_state import RetrievalState
from .knowledge_pipeline.search_stage import run_search_loop
from .knowledge_pipeline.trace import attach_retrieval_trace
from .llm_call_counter import LlmCallCounter
from .retrieval import HybridIndex, SearchResult
from .settings import RagSettings

KnowledgeLLM = TypeVar("KnowledgeLLM")


@dataclass(frozen=True)
class _RetrievalState(RetrievalState):
    """Backward-compatible alias for RetrievalState."""


class HybridKnowledgeService:
    """Default Knowledge Service adapter (spec §8.2), wraps ``HybridIndex``."""

    def __init__(
        self,
        settings: RagSettings,
        index: HybridIndex,
        model: BaseChatModel | None = None,
        release_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.index = index
        self.model = model
        self.release_id = release_id
        self.last_llm_call_count = 0
        self._retrieval_cache: OrderedDict[
            tuple[str, frozenset[str], str, str, int, float], list[SearchResult]
        ] = OrderedDict()

    async def search(
        self,
        query: str,
        user_context: UserContext,
        *,
        correlation_id: str | None = None,
        call_counter: LlmCallCounter | None = None,
        execution_context: ExecutionContext | None = None,
        answer_model: BaseChatModel | None = None,
        request: AgentRequest | None = None,
    ) -> KnowledgeResult:
        del correlation_id  # reserved for cross-service correlation
        return await run_search_loop(
            query=query,
            user_context=user_context,
            call_counter=call_counter,
            execution_context=execution_context,
            answer_model=answer_model,
            request=request,
            default_model=self.model,
            max_retrieval_rewrites=self.settings.max_retrieval_rewrites,
            min_score=self.settings.min_score,
            enable_adaptive_query_tiers=self.settings.enable_adaptive_query_tiers,
            retrieve=self._retrieve,
            documents_are_relevant=self._documents_are_relevant,
            generate=self._generate,
            rewrite=self._rewrite,
            with_trace=self._with_trace,
            limit_result=self._limit_result,
            no_answer=self._no_answer,
            set_llm_count=lambda count: setattr(self, "last_llm_call_count", count),
        )

    async def _invoke_llm(
        self,
        operation: Callable[[], Awaitable[KnowledgeLLM]],
        *,
        component: str,
        execution_context: ExecutionContext | None,
        counter: LlmCallCounter,
    ) -> KnowledgeLLM:
        if execution_context is not None:
            return await execution_context.run_llm(operation, component=component)
        counter.increment()
        return await operation()

    @staticmethod
    def _with_trace(
        result: KnowledgeResult,
        state: _RetrievalState,
        *,
        execution_context: ExecutionContext | None,
        fallback_path: str,
        terminal_reason: str | None,
    ) -> KnowledgeResult:
        selected_backend = (
            execution_context.selected_knowledge_backend
            if execution_context is not None
            else "HYBRID"
        )
        return attach_retrieval_trace(
            result,
            raw_user_utterance=state.raw_user_utterance,
            resolved_issue_query=state.resolved_issue_query,
            search_query=state.search_query,
            facet_queries=state.facet_queries,
            selected_backend=selected_backend,
            attempts=state.trace_attempts,
            stage_timings_ms=state.stage_timings_ms,
            fallback_path=fallback_path,
            terminal_reason=terminal_reason,
            query_tier=state.query_tier,
        )

    async def _retrieve(
        self, state: _RetrievalState, groups: set[str]
    ) -> _RetrievalState:
        host = RetrievalHost(
            search_with_timings=self.index.search_with_timings,
            inject_enterprise_app_evidence=self._inject_enterprise_app_evidence,
            select_document_chunks=self._select_document_chunks,
            top_k=self.settings.top_k,
            min_score=self.settings.min_score,
            deployment_environment=self.settings.deployment_environment,
            release_id=self.release_id or "",
            retrieval_cache=self._retrieval_cache,
        )
        return await run_retrieve(
            host,
            state,
            groups,
            state_factory=_RetrievalState,
        )

    @classmethod
    def _filter_cross_scenario_chunks(
        cls,
        query: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        return filter_cross_scenario_chunks(query, results)

    def _inject_enterprise_app_evidence(
        self,
        query: str,
        results: list[SearchResult],
        *,
        groups: set[str],
        environment: str,
    ) -> list[SearchResult]:
        return inject_enterprise_app_evidence(
            query,
            results,
            index_chunks=self.index.chunks,
            groups=groups,
            environment=environment,
        )

    def _select_document_chunks(
        self,
        query: str,
        results: list[SearchResult],
    ) -> tuple[list[SearchResult], bool]:
        return select_document_chunks(
            query,
            results,
            document_key=self._document_key,
            index_chunks=self.index.chunks,
            top_k=self.settings.top_k,
            max_chunks_per_document=getattr(
                self.settings, "max_chunks_per_document", None
            ),
        )

    @staticmethod
    def _canonical_version_results(
        results: list[SearchResult],
    ) -> list[SearchResult]:
        return canonical_version_results(results)

    def _evaluate_retrieval_confidence(
        self,
        state: _RetrievalState,
    ) -> tuple[str, bool]:
        return evaluate_retrieval_confidence(
            query=state.resolved_issue_query,
            results=state.results,
            min_score=self.settings.min_score,
            filter_displaced_top1=state.filter_displaced_top1,
        )

    async def _documents_are_relevant(
        self,
        state: _RetrievalState,
        counter: LlmCallCounter,
        *,
        execution_context: ExecutionContext | None = None,
        model: BaseChatModel | None = None,
    ) -> bool:
        return await grade_documents_are_relevant(
            state,
            min_score=self.settings.min_score,
            skip_relevance_llm_on_high_confidence=getattr(
                self.settings, "skip_relevance_llm_on_high_confidence", True
            ),
            answer_model=self.model if model is None else model,
            invoke_llm=self._invoke_llm,
            counter=counter,
            execution_context=execution_context,
        )

    async def _rewrite(
        self,
        state: _RetrievalState,
        counter: LlmCallCounter,
        *,
        execution_context: ExecutionContext | None = None,
        model: BaseChatModel | None = None,
    ) -> _RetrievalState:
        answer_model = self.model if model is None else model
        if answer_model is None:
            raise RuntimeError("rewrite requires a chat model")
        return await rewrite_search_query(
            state,
            answer_model=answer_model,
            invoke_llm=self._invoke_llm,
            counter=counter,
            execution_context=execution_context,
            state_factory=_RetrievalState,
        )

    def _citation_for(
        self,
        result: SearchResult,
        *,
        evidence_results: list[SearchResult] | None = None,
    ) -> Citation:
        return build_citation(
            result,
            release_id=self.release_id,
            source_base_url=self.settings.source_base_url,
            evidence_results=evidence_results,
        )

    @staticmethod
    def _retrieval_evidence(results: list[SearchResult]) -> str | None:
        return retrieval_evidence(results)

    @staticmethod
    def _document_key(result: SearchResult) -> str:
        return citation_document_key(result)

    def _unique_citations(
        self,
        results: list[SearchResult],
        *,
        include_retrieval_evidence: bool,
    ) -> list[Citation]:
        return unique_citations(
            results,
            citation_for=self._citation_for,
            include_retrieval_evidence=include_retrieval_evidence,
        )

    def _deterministic_grounded_answer(
        self,
        results: list[SearchResult],
        *,
        include_retrieval_evidence: bool,
    ) -> KnowledgeResult:
        return build_deterministic_grounded_answer(
            results,
            include_retrieval_evidence=include_retrieval_evidence,
            citation_for=self._citation_for,
            images_for=self._images_for,
        )

    def _collect_images(self, results: list[SearchResult]) -> list[AgentImage]:
        from .knowledge_pipeline.citation_io import collect_images

        return collect_images(
            results,
            release_id=self.release_id,
            max_images=self.settings.max_images,
        )

    def _images_for(self, cited_results: list[SearchResult]) -> list[AgentImage]:
        return images_for_cited_results(
            cited_results,
            index_chunks=self.index.chunks,
            release_id=self.release_id,
            max_images=self.settings.max_images,
        )

    @staticmethod
    def _prune_unbacked_sentences_and_citations(
        text: str,
        common_doc_keys: set[str],
        resolve_doc_key: Callable[[int], str | None],
    ) -> str:
        return prune_unbacked_sentences_and_citations(
            text, common_doc_keys, resolve_doc_key
        )

    @staticmethod
    def _prune_uncited_material_sentences(text: str) -> str:
        return prune_uncited_material_sentences(text)

    async def _generate(
        self,
        state: _RetrievalState,
        counter: LlmCallCounter,
        *,
        execution_context: ExecutionContext | None = None,
        model: BaseChatModel | None = None,
        include_retrieval_evidence: bool,
    ) -> KnowledgeResult:
        return await generate_grounded_answer(
            _HybridGenerationHost(self),
            state,
            counter,
            execution_context=execution_context,
            model=self.model if model is None else model,
            include_retrieval_evidence=include_retrieval_evidence,
        )

    async def _repair_claims_with_model(
        self,
        model: BaseChatModel,
        *,
        answer: str,
        results: list[SearchResult],
        counter: LlmCallCounter,
        execution_context: ExecutionContext | None = None,
    ) -> list[GroundedClaim]:
        return await repair_claims_with_model(
            model,
            answer=answer,
            results=results,
            counter=counter,
            invoke_llm=self._invoke_llm,
            execution_context=execution_context,
        )

    @classmethod
    def _sanitize_answer_security(cls, answer: str) -> str:
        return sanitize_answer_security(answer)

    @classmethod
    def _repair_structured_answer(
        cls,
        response: StructuredKnowledgeAnswer,
    ) -> StructuredKnowledgeAnswer:
        return repair_structured_answer(response)

    @staticmethod
    def _structured_answer_is_grounded(
        answer: StructuredKnowledgeAnswer,
        results: list[SearchResult],
    ) -> bool:
        return structured_answer_is_grounded(answer, results)

    @staticmethod
    def _answer_passes_safety_checks(answer: str) -> bool:
        return answer_passes_safety_checks(answer)

    def _limit_result(self, terminal_reason: str) -> KnowledgeResult:
        return KnowledgeResult(
            found=False,
            answer="",
            sources=[],
            images=[],
            backend="HYBRID",
            terminalReason=terminal_reason,
        )

    def _no_answer(self) -> KnowledgeResult:
        # Spec §8.4: miss must not invent sources/images; caller owns wording.
        return KnowledgeResult(
            found=False,
            answer="",
            sources=[],
            images=[],
            backend="HYBRID",
        )


__all__ = ["HybridKnowledgeService", "KnowledgeLLM", "_RetrievalState"]
