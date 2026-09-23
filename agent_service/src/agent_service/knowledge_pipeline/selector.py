"""Document-chunk selection policies for retrieval context (pure)."""

from __future__ import annotations

import re
from collections.abc import Sequence

from agent_service.retrieval import SearchResult, tokenize

from .relevance import primary_distinctive_tokens

_PROCEDURE_QUERY_MARKERS: tuple[str, ...] = (
    "順序",
    "步驟",
    "首次設定",
    "流程",
    "安裝手冊",
    "如何設定",
    "安裝步驟",
    "設定順序",
    "視覺順序",
    "建置順序",
    "操作順序",
)
_ERROR_BRANCH_QUERY_MARKERS: tuple[str, ...] = (
    "分流",
    "錯誤時",
    "各錯誤",
    "不同錯誤",
    "FortiClient 錯誤",
    "forticlient 錯誤",
)
_MULTI_SECTION_QUERY_MARKERS: tuple[str, ...] = (
    "分別",
    "哪些問題類型",
    "跨類型",
    "各情境",
    "不同情境",
    "各類型",
    "分別規定",
)
_COMPARISON_QUERY_MARKERS: tuple[str, ...] = (
    "有何不同",
    "不同之處",
    "差異",
    "比較",
    # Same-document discrimination (“are these the same doc?”).
    "是不是同一份",
    "是不是同一篇",
    "是不是同一個",
    "同一份",
    "同一篇",
    "vs",
)
_ADJACENT_PRODUCT_PAIR_MARKERS: tuple[tuple[str, str], ...] = (
    ("樹精靈", "超音樹"),
)
_NUMBERED_SECTION_RE = re.compile(r"^(?:[#\s]*\d+[\.\-\s]|目錄)")


def query_asks_for_procedure_selection(query: str) -> bool:
    return any(marker in query for marker in _PROCEDURE_QUERY_MARKERS)


def query_asks_for_error_branch_selection(query: str) -> bool:
    return any(marker in query for marker in _ERROR_BRANCH_QUERY_MARKERS)


def query_asks_for_comparison(query: str) -> bool:
    """True when the query asks to compare entities/docs (needs multi-doc Top-k)."""
    text = query or ""
    if any(marker in text for marker in _COMPARISON_QUERY_MARKERS):
        return True
    if "vs" in text.casefold():
        return True
    # Naming both adjacent products in one ask is discrimination even without
    # 「是不是同一份」/「vs」(Playground often uses short「A vs B」or「A跟B」).
    return any(
        left in text and right in text for left, right in _ADJACENT_PRODUCT_PAIR_MARKERS
    )


def query_asks_for_multi_section_selection(query: str) -> bool:
    return any(marker in query for marker in _MULTI_SECTION_QUERY_MARKERS)


def max_chunks_for_query(
    *,
    query: str,
    default_max_chunks: int,
) -> int:
    if (
        query_asks_for_multi_section_selection(query)
        or query_asks_for_procedure_selection(query)
        or query_asks_for_error_branch_selection(query)
    ):
        return 6
    return default_max_chunks


def is_numbered_section(section: str | None) -> bool:
    if not section:
        return False
    return bool(_NUMBERED_SECTION_RE.match(section.strip()))


def section_sort_key(result: SearchResult) -> tuple[int, str]:
    section = result.chunk.section or ""
    match = re.search(r"(\d+)", section)
    number = int(match.group(1)) if match else 999
    return (number, section)


def document_has_competitive_overlap(
    *,
    query: str,
    leader: SearchResult,
    candidates: Sequence[SearchResult],
    overlap_ratio: float,
) -> bool:
    query_tokens = primary_distinctive_tokens(query)
    leader_tokens = set(tokenize(f"{leader.chunk.title}\n{leader.chunk.content}"))
    leader_overlap = len(query_tokens & leader_tokens)
    if not leader_overlap:
        return False
    candidate_tokens: set[str] = set()
    for candidate in candidates:
        candidate_tokens.update(
            tokenize(f"{candidate.chunk.title}\n{candidate.chunk.content}")
        )
    candidate_overlap = len(query_tokens & candidate_tokens)
    return candidate_overlap / leader_overlap >= overlap_ratio


def top1_was_displaced(
    *,
    raw_top1: SearchResult | None,
    selected: Sequence[SearchResult],
    document_key,
    score_gap: float = 0.15,
) -> bool:
    if raw_top1 is None or not selected:
        return False
    return (
        document_key(raw_top1) != document_key(selected[0])
        or raw_top1.score - selected[0].score > score_gap
    )


__all__ = [
    "document_has_competitive_overlap",
    "is_numbered_section",
    "max_chunks_for_query",
    "query_asks_for_comparison",
    "query_asks_for_error_branch_selection",
    "query_asks_for_multi_section_selection",
    "query_asks_for_procedure_selection",
    "section_sort_key",
    "top1_was_displaced",
]
