"""Tests for HybridKnowledgeService sticky canary serving (spec §48)."""

from __future__ import annotations

from dataclasses import replace

from agent_service.contracts import (
    AgentRequest,
    ConversationIdentity,
    MessageContent,
    UserContext,
    UserIdentity,
)
from agent_service.knowledge_hybrid import HybridKnowledgeService
from agent_service.rag_rollout import VARIANT_D_RRF_CONTEXTUAL_RERANK
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
    assert decision.serve_variant == VARIANT_D_RRF_CONTEXTUAL_RERANK
    assert decision.fusion_mode == "RRF"
    assert decision.reranker_enabled is False


def test_serving_decision_canary_enables_rerank_when_flag_on() -> None:
    settings = replace(
        RagSettings.from_env(),
        rag_canary_percent=100,
        rag_reranker_enabled=True,
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
    assert decision.serve_variant == VARIANT_D_RRF_CONTEXTUAL_RERANK
    assert decision.fusion_mode == "RRF"
    assert decision.reranker_enabled is True


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
