"""Parent / neighbor context expansion after rerank (RAG v2.1 P2).

Retrieve small chunks, then expand the top hits with parent and adjacent
neighbors so the generator sees procedure context, not an isolated sentence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult

_DEFAULT_TOP_SEEDS = 3
_DEFAULT_MAX_EXTRA = 6


def expand_retrieval_context(
    ranked: Sequence[SearchResult],
    *,
    chunk_by_id: Mapping[str, DocumentChunk],
    top_seeds: int = _DEFAULT_TOP_SEEDS,
    max_extra: int = _DEFAULT_MAX_EXTRA,
) -> list[SearchResult]:
    """Append parent/neighbor chunks after the ranked prefix (deduped)."""
    if not ranked or not chunk_by_id:
        return list(ranked)

    seeds = list(ranked[: max(top_seeds, 0)])
    seen = {item.chunk.chunk_id for item in ranked}
    extras: list[SearchResult] = []

    for seed in seeds:
        if len(extras) >= max_extra:
            break
        parent_id = seed.chunk.parent_id
        if parent_id and parent_id not in seen:
            parent = chunk_by_id.get(parent_id)
            if parent is not None:
                extras.append(
                    SearchResult(
                        chunk=parent,
                        score=seed.score,
                        sparse_score=seed.sparse_score,
                        dense_score=seed.dense_score,
                        fusion_score=seed.fusion_score,
                        fusion_rank=seed.fusion_rank,
                        final_rank=None,
                    )
                )
                seen.add(parent_id)
        for neighbor_id in seed.chunk.neighbor_ids or []:
            if len(extras) >= max_extra:
                break
            if neighbor_id in seen:
                continue
            neighbor = chunk_by_id.get(neighbor_id)
            if neighbor is None:
                continue
            extras.append(
                SearchResult(
                    chunk=neighbor,
                    score=seed.score * 0.99,
                    sparse_score=seed.sparse_score,
                    dense_score=seed.dense_score,
                    fusion_score=seed.fusion_score,
                    fusion_rank=seed.fusion_rank,
                    final_rank=None,
                )
            )
            seen.add(neighbor_id)

    return list(ranked) + extras


__all__ = ["expand_retrieval_context"]
