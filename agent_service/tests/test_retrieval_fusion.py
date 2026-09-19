"""Unit tests for Reciprocal Rank Fusion (RAG v2 Milestone 1 / spec §41)."""

from __future__ import annotations

import pytest

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult
from agent_service.retrieval_fusion import legacy_weighted_hybrid_rank, reciprocal_rank_fusion


def _chunk(chunk_id: str, title: str = "doc") -> DocumentChunk:
    return DocumentChunk(chunk_id=chunk_id, title=title, source_path=f"{chunk_id}.md", content=title)


def _result(chunk_id: str, *, sparse: float = 0.0, dense: float | None = None) -> SearchResult:
    return SearchResult(
        chunk=_chunk(chunk_id),
        score=sparse,
        sparse_score=sparse,
        dense_score=dense,
    )


def test_rrf_prefers_consensus_over_sparse_only_leader() -> None:
    sparse = [_result("a", sparse=0.9), _result("b", sparse=0.8), _result("c", sparse=0.1)]
    dense = [_result("b", dense=0.95), _result("c", dense=0.9), _result("a", dense=0.2)]
    fused = reciprocal_rank_fusion(sparse_results=sparse, dense_results=dense, k=60)
    assert fused[0].chunk.chunk_id == "b"
    assert fused[0].fusion_score is not None
    assert fused[0].sparse_rank == 2
    assert fused[0].dense_rank == 1


def test_dense_only_strong_candidate_survives() -> None:
    sparse = [_result("a", sparse=0.5)]
    dense = [_result("z", dense=0.99), _result("a", dense=0.1)]
    fused = reciprocal_rank_fusion(sparse_results=sparse, dense_results=dense, k=60)
    ids = [item.chunk.chunk_id for item in fused]
    assert "z" in ids
    assert fused[0].chunk.chunk_id in {"z", "a"}


def test_duplicate_chunk_is_deduplicated() -> None:
    sparse = [_result("a", sparse=0.9)]
    dense = [_result("a", dense=0.9)]
    fused = reciprocal_rank_fusion(sparse_results=sparse, dense_results=dense, k=60)
    assert len(fused) == 1
    assert fused[0].chunk.chunk_id == "a"


def test_weights_change_ordering() -> None:
    sparse = [_result("sparse_win", sparse=1.0), _result("dense_win", sparse=0.1)]
    dense = [_result("dense_win", dense=1.0), _result("sparse_win", dense=0.1)]
    sparse_heavy = reciprocal_rank_fusion(
        sparse_results=sparse,
        dense_results=dense,
        k=60,
        sparse_weight=5.0,
        dense_weight=0.1,
    )
    dense_heavy = reciprocal_rank_fusion(
        sparse_results=sparse,
        dense_results=dense,
        k=60,
        sparse_weight=0.1,
        dense_weight=5.0,
    )
    assert sparse_heavy[0].chunk.chunk_id == "sparse_win"
    assert dense_heavy[0].chunk.chunk_id == "dense_win"


def test_rrf_ordering_is_deterministic() -> None:
    sparse = [_result("b", sparse=0.5), _result("a", sparse=0.5)]
    dense = [_result("a", dense=0.5), _result("b", dense=0.5)]
    first = [item.chunk.chunk_id for item in reciprocal_rank_fusion(
        sparse_results=sparse, dense_results=dense, k=60
    )]
    second = [item.chunk.chunk_id for item in reciprocal_rank_fusion(
        sparse_results=sparse, dense_results=dense, k=60
    )]
    assert first == second


def test_empty_lists_return_empty() -> None:
    assert reciprocal_rank_fusion(sparse_results=[], dense_results=[], k=60) == []


def test_invalid_k_raises() -> None:
    with pytest.raises(ValueError, match="rrf k"):
        reciprocal_rank_fusion(sparse_results=[], dense_results=[], k=0)


def test_legacy_weighted_prefers_dense_blend() -> None:
    ranked = legacy_weighted_hybrid_rank(
        [
            _result("sparse-lead", sparse=1.0, dense=0.1),
            _result("dense-lead", sparse=0.5, dense=1.0),
        ]
    )
    assert ranked[0].chunk.chunk_id == "dense-lead"
