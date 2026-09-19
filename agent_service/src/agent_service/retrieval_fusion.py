"""Reciprocal Rank Fusion for hybrid retrieval (RAG v2 Milestone 1).

Pure functions only — no coupling to HybridIndex, KnowledgeService, or Workflow.
"""

from __future__ import annotations

from .retrieval import SearchResult


def evidence_gate_score(result: SearchResult) -> float:
    """[0,1]-scale score for min_score / confidence gates.

    RRF fusion magnitudes are tiny (~1/(k+rank)); relevance thresholds were
    calibrated on sparse/dense evidence scores. Ranking still follows
    ``fusion_score`` / list order from RRF.
    """
    dense = result.dense_score
    if dense is None:
        return float(result.sparse_score)
    return max(float(result.sparse_score), float(dense))


def _merge_rrf_candidate(
    existing: SearchResult | None,
    incoming: SearchResult,
) -> SearchResult:
    if existing is None:
        return incoming
    return SearchResult(
        chunk=existing.chunk,
        score=existing.score,
        sparse_score=existing.sparse_score,
        dense_score=(
            incoming.dense_score
            if incoming.dense_score is not None
            else existing.dense_score
        ),
        sparse_rank=existing.sparse_rank,
        dense_rank=existing.dense_rank,
        fusion_score=existing.fusion_score,
        fusion_rank=existing.fusion_rank,
        rerank_score=existing.rerank_score,
        rerank_rank=existing.rerank_rank,
        final_rank=existing.final_rank,
    )


def _rrf_ranked_result(
    base: SearchResult,
    *,
    chunk_id: str,
    fusion_score: float,
    fusion_rank: int,
    sparse_rank: dict[str, int],
    dense_rank: dict[str, int],
) -> SearchResult:
    return SearchResult(
        chunk=base.chunk,
        score=round(evidence_gate_score(base), 6),
        sparse_score=base.sparse_score,
        dense_score=base.dense_score,
        sparse_rank=sparse_rank.get(chunk_id),
        dense_rank=dense_rank.get(chunk_id),
        fusion_score=round(fusion_score, 6),
        fusion_rank=fusion_rank,
        rerank_score=base.rerank_score,
        rerank_rank=base.rerank_rank,
        final_rank=fusion_rank,
    )


def reciprocal_rank_fusion(
    *,
    sparse_results: list[SearchResult],
    dense_results: list[SearchResult],
    k: int,
    sparse_weight: float = 1.0,
    dense_weight: float = 1.0,
) -> list[SearchResult]:
    """Fuse sparse and dense ranked lists with weighted RRF.

    Candidates are keyed by ``chunk.chunk_id``. ACL filtering must already have
    been applied before results enter this function.

    ``fusion_score`` holds the RRF value used for ordering; ``score`` keeps the
    evidence gate scale so ``min_score`` / high-confidence checks stay valid.
    """
    if k < 1:
        raise ValueError("rrf k must be >= 1")
    if sparse_weight < 0 or dense_weight < 0:
        raise ValueError("RRF weights must be non-negative")

    scores: dict[str, float] = {}
    sparse_rank: dict[str, int] = {}
    dense_rank: dict[str, int] = {}
    by_id: dict[str, SearchResult] = {}

    for rank, result in enumerate(sparse_results, start=1):
        chunk_id = result.chunk.chunk_id
        sparse_rank[chunk_id] = rank
        scores[chunk_id] = scores.get(chunk_id, 0.0) + sparse_weight / (k + rank)
        by_id[chunk_id] = result

    for rank, result in enumerate(dense_results, start=1):
        chunk_id = result.chunk.chunk_id
        dense_rank[chunk_id] = rank
        scores[chunk_id] = scores.get(chunk_id, 0.0) + dense_weight / (k + rank)
        by_id[chunk_id] = _merge_rrf_candidate(by_id.get(chunk_id), result)

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        _rrf_ranked_result(
            by_id[chunk_id],
            chunk_id=chunk_id,
            fusion_score=fusion_score,
            fusion_rank=fusion_rank,
            sparse_rank=sparse_rank,
            dense_rank=dense_rank,
        )
        for fusion_rank, (chunk_id, fusion_score) in enumerate(ordered, start=1)
    ]


def legacy_weighted_hybrid_rank(
    results: list[SearchResult],
    *,
    sparse_coefficient: float = 0.45,
    dense_coefficient: float = 0.55,
) -> list[SearchResult]:
    """Pre-M7 linear blend — offline §45 / shadow baseline A only.

    Production ``HybridIndex.search`` no longer uses this path (M7).
    """
    ranked: list[SearchResult] = []
    for item in results:
        dense = item.dense_score
        if dense is None:
            score = item.sparse_score
        else:
            score = sparse_coefficient * item.sparse_score + dense_coefficient * dense
        ranked.append(
            SearchResult(
                chunk=item.chunk,
                score=round(score, 6),
                sparse_score=item.sparse_score,
                dense_score=item.dense_score,
                sparse_rank=item.sparse_rank,
                dense_rank=item.dense_rank,
            )
        )
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def fuse_hybrid_candidates(
    results: list[SearchResult],
    *,
    query: str,
    limit: int,
    sparse_candidate_k: int,
    dense_candidate_k: int,
    fusion_candidate_k: int,
    rrf_k: int,
    sparse_weight: float,
    dense_weight: float,
    legacy_weighted: bool,
) -> list[SearchResult]:
    """Rank scored candidates via Soft-best RRF or legacy weighted blend."""
    from .reranker import apply_error_code_guard

    if legacy_weighted:
        ranked = legacy_weighted_hybrid_rank(results)
        return [result for result in ranked[:limit] if result.score > 0]

    sparse_ranked = sorted(
        (
            SearchResult(
                chunk=item.chunk,
                score=item.sparse_score,
                sparse_score=item.sparse_score,
                dense_score=item.dense_score,
            )
            for item in results
            if item.sparse_score > 0
        ),
        key=lambda item: item.sparse_score,
        reverse=True,
    )[:sparse_candidate_k]
    dense_ranked = sorted(
        (
            SearchResult(
                chunk=item.chunk,
                score=item.dense_score or 0.0,
                sparse_score=item.sparse_score,
                dense_score=item.dense_score,
            )
            for item in results
            if item.dense_score is not None and item.dense_score > 0
        ),
        key=lambda item: item.dense_score or 0.0,
        reverse=True,
    )[:dense_candidate_k]
    fused = reciprocal_rank_fusion(
        sparse_results=sparse_ranked,
        dense_results=dense_ranked,
        k=rrf_k,
        sparse_weight=sparse_weight,
        dense_weight=dense_weight,
    )
    take = min(limit, fusion_candidate_k)
    filtered = [result for result in fused[:take] if result.score > 0]
    return apply_error_code_guard(query, filtered)


__all__ = [
    "evidence_gate_score",
    "fuse_hybrid_candidates",
    "legacy_weighted_hybrid_rank",
    "reciprocal_rank_fusion",
]
