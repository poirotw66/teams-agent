"""Serving / canary helpers for HybridKnowledgeService."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any

from .contracts import AgentRequest
from .knowledge_pipeline.retrieval_stage import RetrievalHost
from .rag_rollout import (
    VARIANT_A_WEIGHTED,
    VARIANT_D_RRF_CONTEXTUAL_RERANK,
    RagServingDecision,
    select_rag_serving_variant,
)
from .reranker import Reranker
from .retrieval import HybridIndex, SearchResult
from .settings import RagSettings


def resolve_serving_decision(
    *,
    settings: RagSettings,
    index: HybridIndex,
    request: AgentRequest | None,
) -> RagServingDecision:
    tenant = "default"
    conversation_id = "anonymous"
    if request is not None:
        tenant = (request.conversation.tenantId or "default").strip() or "default"
        conversation_id = (
            request.conversation.conversationId or request.requestId or "anonymous"
        ).strip() or "anonymous"
    return select_rag_serving_variant(
        tenant=tenant,
        conversation_id=conversation_id,
        canary_percent=int(getattr(settings, "rag_canary_percent", 0)),
        canary_variant=VARIANT_D_RRF_CONTEXTUAL_RERANK,
        baseline_variant=VARIANT_A_WEIGHTED,
        shadow_enabled=bool(getattr(settings, "rag_shadow_enabled", False)),
        baseline_fusion_mode=str(
            getattr(index, "fusion_mode", None)
            or getattr(settings, "rag_fusion_mode", "RRF")
        ),
        global_reranker_enabled=bool(getattr(settings, "rag_reranker_enabled", False)),
    )


def build_retrieval_host(
    *,
    settings: RagSettings,
    index: HybridIndex,
    release_id: str,
    retrieval_cache: MutableMapping[tuple[Any, ...], list[SearchResult]],
    reranker: Reranker | None,
    serving: RagServingDecision | None,
    inject_enterprise_app_evidence: Callable[..., list[SearchResult]],
    select_document_chunks: Callable[[str, list[SearchResult]], tuple[list[SearchResult], bool]],
) -> RetrievalHost:
    decision = serving or RagServingDecision(
        serve_variant=VARIANT_A_WEIGHTED,
        is_canary=False,
        canary_percent=0,
        shadow_enabled=False,
        fusion_mode=str(getattr(index, "fusion_mode", "RRF")),
        reranker_enabled=bool(getattr(settings, "rag_reranker_enabled", True)),
    )
    fusion_mode = decision.fusion_mode
    reranker_enabled = decision.reranker_enabled
    if decision.shadow_enabled and not decision.is_canary:
        fusion_mode = str(getattr(index, "fusion_mode", "RRF"))
        reranker_enabled = bool(getattr(settings, "rag_reranker_enabled", True))
    return RetrievalHost(
        search_with_timings=index.search_with_timings,
        inject_enterprise_app_evidence=inject_enterprise_app_evidence,
        select_document_chunks=select_document_chunks,
        top_k=settings.top_k,
        min_score=settings.min_score,
        deployment_environment=settings.deployment_environment,
        release_id=release_id,
        retrieval_cache=retrieval_cache,
        reranker=reranker,
        rerank_candidate_k=int(getattr(settings, "rag_rerank_candidate_k", 24)),
        reranker_enabled=reranker_enabled,
        reranker_min_tier=str(
            getattr(settings, "rag_reranker_min_tier", "standard")
        ).lower(),
        reranker_model=str(getattr(settings, "rag_reranker_model", None) or "noop"),
        fusion_mode=fusion_mode,
        rrf_k=int(getattr(index, "rrf_k", 60)),
        contextualization_version=next(
            (
                chunk.contextualization_version or ""
                for chunk in index.chunks
                if chunk.contextualization_version
            ),
            "",
        ),
    )


__all__ = ["build_retrieval_host", "resolve_serving_decision"]
