"""Tests for HybridKnowledgeService sticky canary serving (spec §48)."""

from __future__ import annotations

from dataclasses import replace

from agent_service.contracts import (
    AgentRequest,
    ConversationIdentity,
    MessageContent,
    UserIdentity,
)
from agent_service.knowledge_hybrid import HybridKnowledgeService
from agent_service.rag_rollout import VARIANT_C_RRF_RERANK
from agent_service.retrieval import HybridIndex
from agent_service.settings import RagSettings
from knowledge_core.document_models import DocumentChunk


def _request(*, conversation_id: str, tenant: str = "acme") -> AgentRequest:
    return AgentRequest(
        requestId="req-1",
        channel="playground",
        conversation=ConversationIdentity(
            tenantId=tenant,
            conversationId=conversation_id,
        ),
        user=UserIdentity(teamsUserId="u1"),
        message=MessageContent(text="VPN Permission denied (-455)"),
    )


def test_serving_decision_canary_uses_rrf_when_percent_100() -> None:
    settings = replace(
        RagSettings.from_env(),
        rag_canary_percent=100,
        rag_reranker_enabled=False,
        rag_reranker_model="noop",
    )
    index = HybridIndex(
        [
            DocumentChunk(
                chunk_id="c1",
                title="VPN",
                source_path="vpn.md",
                content="Permission denied (-455)",
            )
        ],
        fusion_mode="WEIGHTED",
    )
    service = HybridKnowledgeService(settings, index)
    decision = service._serving_decision(_request(conversation_id="always-canary"))
    assert decision.is_canary is True
    assert decision.serve_variant == VARIANT_C_RRF_RERANK
    assert decision.fusion_mode == "RRF"
    assert decision.reranker_enabled is False


def test_serving_decision_canary_enables_rerank_when_model_configured() -> None:
    """Canary enables reranker even when production baseline has it disabled."""
    settings = replace(
        RagSettings.from_env(),
        rag_canary_percent=100,
        rag_reranker_enabled=False,
        rag_reranker_model="listwise",
    )
    index = HybridIndex(
        [
            DocumentChunk(
                chunk_id="c1",
                title="VPN",
                source_path="vpn.md",
                content="Permission denied (-455)",
            )
        ],
        fusion_mode="WEIGHTED",
    )
    service = HybridKnowledgeService(settings, index)
    decision = service._serving_decision(_request(conversation_id="always-canary"))
    assert decision.serve_variant == VARIANT_C_RRF_RERANK
    assert decision.fusion_mode == "RRF"
    assert decision.reranker_enabled is True


def test_serving_decision_baseline_keeps_rerank_off_when_canary_active() -> None:
    """At 0% canary, baseline never turns reranker on when rag_reranker_enabled=False."""
    settings = replace(
        RagSettings.from_env(),
        rag_canary_percent=0,
        rag_reranker_enabled=False,
        rag_reranker_model="listwise",
    )
    index = HybridIndex(
        [
            DocumentChunk(
                chunk_id="c1",
                title="VPN",
                source_path="vpn.md",
                content="Permission denied (-455)",
            )
        ],
        fusion_mode="RRF",
    )
    service = HybridKnowledgeService(settings, index)
    decision = service._serving_decision(_request(conversation_id="baseline-request"))
    assert decision.is_canary is False
    assert decision.reranker_enabled is False
    assert decision.serve_variant == "BASELINE"


def test_serving_decision_zero_percent_uses_production_knobs() -> None:
    settings = replace(
        RagSettings.from_env(),
        rag_canary_percent=0,
        rag_fusion_mode="RRF",
        rag_reranker_enabled=True,
    )
    index = HybridIndex(
        [
            DocumentChunk(
                chunk_id="c1",
                title="VPN",
                source_path="vpn.md",
                content="body",
            )
        ],
        fusion_mode="RRF",
    )
    service = HybridKnowledgeService(settings, index)
    decision = service._serving_decision(_request(conversation_id="x"))
    assert decision.is_canary is False
    assert decision.fusion_mode == "RRF"
    assert decision.reranker_enabled is True


def test_retrieval_cache_key_isolates_candidate_limit() -> None:
    """Baseline (e.g. 20 candidates) must not pollute canary (e.g. 24 candidates)."""
    from agent_service.knowledge_pipeline.retriever import make_retrieval_cache_key

    baseline_key = make_retrieval_cache_key(
        "vpn error",
        groups=frozenset({"grp-vpn"}),
        environment="prod",
        release_id="rel-1",
        top_k=4,
        min_score=0.08,
        candidate_limit=20,
        fusion_candidate_k=20,
    )
    canary_key = make_retrieval_cache_key(
        "vpn error",
        groups=frozenset({"grp-vpn"}),
        environment="prod",
        release_id="rel-1",
        top_k=4,
        min_score=0.08,
        candidate_limit=24,
        fusion_candidate_k=20,
    )
    assert baseline_key != canary_key
    cache: dict[tuple, list] = {baseline_key: ["result_1"] * 20}
    assert canary_key not in cache
