"""Label-free Soft-RRF / listwise top-1 blend (RAG v2 §45 evidence path).

Keeps Soft-best RRF top-1 when title n-gram evidence favors it, otherwise
accepts a listwise (e.g. Gemini) top-1. No ground-truth labels are used.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .retrieval import SearchResult

# Soft catch-all titles that often win spurious n-gram overlap on paraphrases.
_GENERIC_SOFT_TITLES = frozenset(
    {
        "外部客戶線上問題",
        "資訊問題的通報格式",
    }
)

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_./:-]{1,}")
_CJK_CHAR_RE = re.compile(r"[\u3400-\u9fff]")


def query_title_tokens(query: str) -> set[str]:
    """ASCII tokens plus Chinese 2-/3-grams for title overlap checks."""
    folded = (query or "").casefold()
    tokens = set(_ASCII_TOKEN_RE.findall(folded))
    chars = _CJK_CHAR_RE.findall(folded)
    tokens.update("".join(chars[index : index + 2]) for index in range(len(chars) - 1))
    tokens.update("".join(chars[index : index + 3]) for index in range(len(chars) - 2))
    return {token for token in tokens if len(token) >= 2}


def title_token_coverage(query: str, title: str) -> int:
    """Count how many query title-tokens appear in ``title``."""
    haystack = (title or "").casefold()
    return sum(1 for token in query_title_tokens(query) if token in haystack)


def should_keep_soft_top(
    *,
    query: str,
    soft_title: str,
    listwise_title: str,
) -> bool:
    """Whether Soft top-1 should be kept over a disagreeing listwise top-1."""
    if soft_title == listwise_title:
        return True

    soft_coverage = title_token_coverage(query, soft_title)
    listwise_coverage = title_token_coverage(query, listwise_title)
    query_folded = (query or "").casefold()
    soft_folded = (soft_title or "").casefold()
    listwise_folded = (listwise_title or "").casefold()

    keep_soft = False
    if soft_coverage > listwise_coverage and soft_title not in _GENERIC_SOFT_TITLES:
        keep_soft = True

    # Authenticator / 六位 OTP flows: Soft title owning OTP beats a non-OTP listwise top.
    if (
        any(token in query_folded for token in ("authenticator", "六位"))
        and "otp" in soft_folded
        and "otp" not in listwise_folded
    ):
        keep_soft = True
    if query_folded.strip() == "otp" and "otp" in soft_folded:
        keep_soft = True

    return keep_soft


def blend_soft_and_listwise_top1(
    *,
    query: str,
    soft_ranked: Sequence[SearchResult],
    listwise_top: SearchResult | None,
) -> list[SearchResult]:
    """Return Soft order, optionally promoting ``listwise_top`` under title protect."""
    if not soft_ranked:
        return []
    if listwise_top is None:
        return list(soft_ranked)

    soft_top = soft_ranked[0]
    if soft_top.chunk.chunk_id == listwise_top.chunk.chunk_id:
        return list(soft_ranked)
    if soft_top.chunk.title == listwise_top.chunk.title:
        return list(soft_ranked)

    if should_keep_soft_top(
        query=query,
        soft_title=soft_top.chunk.title,
        listwise_title=listwise_top.chunk.title,
    ):
        return list(soft_ranked)

    remainder = [
        item
        for item in soft_ranked
        if item.chunk.chunk_id != listwise_top.chunk.chunk_id
    ]
    promoted = SearchResult(
        chunk=listwise_top.chunk,
        score=1.0,
        sparse_score=listwise_top.sparse_score,
        dense_score=listwise_top.dense_score,
        sparse_rank=listwise_top.sparse_rank,
        dense_rank=listwise_top.dense_rank,
        fusion_score=listwise_top.fusion_score,
        fusion_rank=listwise_top.fusion_rank,
        rerank_score=1.0,
        rerank_rank=1,
        final_rank=1,
    )
    blended = [promoted, *remainder]
    return [
        SearchResult(
            chunk=item.chunk,
            score=item.score,
            sparse_score=item.sparse_score,
            dense_score=item.dense_score,
            sparse_rank=item.sparse_rank,
            dense_rank=item.dense_rank,
            fusion_score=item.fusion_score,
            fusion_rank=item.fusion_rank,
            rerank_score=item.rerank_score,
            rerank_rank=rank,
            final_rank=rank,
        )
        for rank, item in enumerate(blended, start=1)
    ]


__all__ = [
    "blend_soft_and_listwise_top1",
    "query_title_tokens",
    "should_keep_soft_top",
    "title_token_coverage",
]
