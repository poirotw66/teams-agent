"""Tests for RAG v2 shadow/canary rollout helpers (spec §46–§48)."""

from __future__ import annotations

from agent_service.rag_rollout import (
    CANARY_LADDER_PERCENTS,
    VARIANT_A_WEIGHTED,
    VARIANT_C_RRF_RERANK,
    VARIANT_D_RRF_CONTEXTUAL_RERANK,
    next_canary_percent,
    retrieval_knobs_for_variant,
    select_rag_serving_variant,
    top1_changed,
    topk_overlap,
)


def test_canary_percent_zero_honors_reranker_flag() -> None:
    decision = select_rag_serving_variant(
        tenant="t",
        conversation_id="c1",
        canary_percent=0,
        baseline_fusion_mode="RRF",
        global_reranker_enabled=True,
    )
    assert decision.serve_variant == VARIANT_A_WEIGHTED
    assert decision.fusion_mode == "RRF"
    assert decision.reranker_enabled is True


def test_canary_percent_100_always_canary() -> None:
    decision = select_rag_serving_variant(
        tenant="t",
        conversation_id="any",
        canary_percent=100,
    )
    assert decision.is_canary is True
    assert decision.serve_variant == VARIANT_C_RRF_RERANK
    assert decision.fusion_mode == "RRF"
    assert decision.reranker_enabled is False


def test_variant_c_rerank_requires_global_flag() -> None:
    fusion, rerank = retrieval_knobs_for_variant(
        VARIANT_C_RRF_RERANK,
        global_reranker_enabled=False,
    )
    assert fusion == "RRF"
    assert rerank is False
    fusion_on, rerank_on = retrieval_knobs_for_variant(
        VARIANT_C_RRF_RERANK,
        global_reranker_enabled=True,
    )
    assert fusion_on == "RRF"
    assert rerank_on is True


def test_legacy_d_alias_maps_to_rerank_knobs() -> None:
    fusion, rerank = retrieval_knobs_for_variant(
        VARIANT_D_RRF_CONTEXTUAL_RERANK,
        global_reranker_enabled=True,
    )
    assert fusion == "RRF"
    assert rerank is True


def test_canary_sticky_for_same_conversation() -> None:
    first = select_rag_serving_variant(
        tenant="acme",
        conversation_id="sticky-1",
        canary_percent=50,
    )
    second = select_rag_serving_variant(
        tenant="acme",
        conversation_id="sticky-1",
        canary_percent=50,
    )
    assert first == second


def test_canary_ladder_steps() -> None:
    assert CANARY_LADDER_PERCENTS[0] == 5
    assert next_canary_percent(0) == 5
    assert next_canary_percent(5) == 20
    assert next_canary_percent(20) == 50
    assert next_canary_percent(50) == 100
    assert next_canary_percent(100) is None


def test_topk_overlap_and_top1_change() -> None:
    assert top1_changed(["a", "b"], ["a", "c"]) is False
    assert top1_changed(["a"], ["b"]) is True
    assert topk_overlap(["a", "b", "c"], ["b", "c", "d"], k=3) == 0.5
