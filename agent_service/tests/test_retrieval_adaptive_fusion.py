"""Tests for adaptive Soft-RRF weights (RAG v2.1)."""

from __future__ import annotations

from agent_service.retrieval_adaptive_fusion import (
    adaptive_fusion_weights,
    classify_fusion_profile,
)


def test_error_code_query_is_sparse_heavy() -> None:
    weights = adaptive_fusion_weights("Permission denied (-455)")
    assert weights.profile == "error_code"
    assert weights.sparse_weight > weights.dense_weight


def test_product_and_code_profile() -> None:
    assert classify_fusion_profile("VPN (-14) unreachable") == "product_and_code"
    weights = adaptive_fusion_weights("VPN (-14) unreachable")
    assert weights.sparse_weight == 1.5
    assert weights.dense_weight == 1.0


def test_natural_language_keeps_defaults() -> None:
    weights = adaptive_fusion_weights(
        "外面連公司網路一直被拒絕",
        default_sparse_weight=0.5,
        default_dense_weight=1.5,
    )
    assert weights.profile == "natural_language"
    assert weights.sparse_weight == 0.5
    assert weights.dense_weight == 1.5


def test_no_product_specific_fortitoken_branch() -> None:
    # Same profile family whether or not a product brand appears without a code.
    left = classify_fusion_profile("收不到驗證碼怎麼辦")
    right = classify_fusion_profile("FortiToken 收不到 OTP")
    assert left == "natural_language"
    assert right == "natural_language"
