"""Document chunk selection helpers for knowledge pipeline context building."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult, tokenize
from agent_service.retrieval_ranking import (
    evidence_confidence,
    ranking_sort_key,
)

from .relevance import primary_distinctive_tokens
from .selector import (
    document_has_competitive_overlap,
    is_numbered_section,
    max_chunks_for_query,
    query_asks_for_comparison,
    query_asks_for_error_branch_selection,
    query_asks_for_procedure_selection,
    section_sort_key,
)

_MAX_CONTEXT_DOCUMENTS = 3
_MAX_ACCESS_SCOPE_CONTEXT_DOCUMENTS = 4
_MAX_CHUNKS_PER_DOCUMENT = 2
_ACCESS_SCOPE_QUERY_MARKERS: tuple[str, ...] = (
    "權限",
    "存取",
    "可使用",
    "不可使用",
    "所有內部",
    "所有系統",
    "是否代表可存取",
    "能否存取",
    "連線後是否",
)
_DOCUMENT_SELECTION_SCORE_RATIO = 0.7
_DOCUMENT_SELECTION_OVERLAP_RATIO = 0.5
_VPN_PASSWORD_EXPIRY_QUERY_MARKERS: tuple[str, ...] = (
    "密碼到期",
    "怎麼處理",
    "如何處理",
    "要怎麼",
)
_VPN_PASSWORD_HOWTO_MARKERS: tuple[str, ...] = (
    "ctrl + alt + delete",
    "ctrl+alt+delete",
    "實體網路線",
)


def _is_vpn_password_expiry_query(query: str) -> bool:
    query_l = (query or "").casefold()
    if "vpn" not in query_l:
        return False
    return any(marker in (query or "") for marker in _VPN_PASSWORD_EXPIRY_QUERY_MARKERS)


def _group_has_vpn_password_howto(group: Sequence[SearchResult]) -> bool:
    for result in group:
        blob = f"{result.chunk.title}\n{result.chunk.content}".casefold()
        if any(marker in blob for marker in _VPN_PASSWORD_HOWTO_MARKERS):
            return True
    return False


def protect_raw_top1(
    query: str,
    raw_top1: SearchResult,
    filtered_results: list[SearchResult],
) -> list[SearchResult]:
    if raw_top1 in filtered_results or evidence_confidence(raw_top1) < 0.70:
        return filtered_results
    query_tokens = [token for token in tokenize(query) if len(token) > 1]
    top1_text = f"{raw_top1.chunk.title} {raw_top1.chunk.content}".lower()
    if any(token in top1_text for token in query_tokens):
        filtered_results.insert(0, raw_top1)
    return filtered_results


def _best_ranked_in_group(group: Sequence[SearchResult]) -> SearchResult:
    return min(group, key=ranking_sort_key)


def _sibling_title_tokens(
    query: str,
    ranked_documents: Sequence[Sequence[SearchResult]],
) -> frozenset[str]:
    """Distinctive query tokens that appear in at least two document titles.

    Used to keep sibling manuals (e.g. two 大州 docs) above the score floor
    without promoting unrelated single-title matches.
    """
    tokens = primary_distinctive_tokens(query)
    if not tokens or len(ranked_documents) < 2:
        return frozenset()
    titles = [
        (_best_ranked_in_group(group).chunk.title or "").casefold()
        for group in ranked_documents
    ]
    shared: set[str] = set()
    for token in tokens:
        needle = token.casefold()
        if sum(1 for title in titles if needle in title) >= 2:
            shared.add(needle)
    return frozenset(shared)


def _title_matches_sibling_tokens(
    group: Sequence[SearchResult],
    sibling_tokens: frozenset[str],
) -> bool:
    if not sibling_tokens:
        return False
    title = (_best_ranked_in_group(group).chunk.title or "").casefold()
    return any(token in title for token in sibling_tokens)


def _title_query_token_hits(
    group: Sequence[SearchResult],
    query_tokens: frozenset[str],
) -> int:
    if not query_tokens:
        return 0
    title = (_best_ranked_in_group(group).chunk.title or "").casefold()
    return sum(1 for token in query_tokens if token.casefold() in title)


def _prefer_query_titled_documents(
    query: str,
    ranked_documents: Sequence[Sequence[SearchResult]],
    *,
    limit: int,
) -> list[list[SearchResult]]:
    """For comparison queries, keep title-aligned docs ahead of distractors.

    Adjacent-product discrimination (樹精靈 vs 超音樹) often retrieves both
    targets below generic high-score noise; the context-doc cap would otherwise
    drop the second named manual.
    """
    if limit <= 0:
        return []
    documents = list(ranked_documents)
    tokens = frozenset(primary_distinctive_tokens(query))
    if not tokens:
        return documents[:limit]
    titled = [group for group in documents if _title_query_token_hits(group, tokens) > 0]
    untitled = [group for group in documents if _title_query_token_hits(group, tokens) == 0]
    return (titled + untitled)[:limit]


def rank_documents_for_query(
    query: str,
    filtered_results: Sequence[SearchResult],
    *,
    document_key: Callable[[SearchResult], str],
    top_k: int,
) -> list[list[SearchResult]]:
    by_document: dict[str, list[SearchResult]] = {}
    for result in filtered_results:
        by_document.setdefault(document_key(result), []).append(result)

    # Document order follows ranking contract, not evidence confidence.
    ranked_documents = sorted(
        by_document.values(),
        key=lambda group: ranking_sort_key(_best_ranked_in_group(group)),
    )
    if ranked_documents:
        leader = _best_ranked_in_group(ranked_documents[0])
        score_floor = evidence_confidence(leader) * _DOCUMENT_SELECTION_SCORE_RATIO
        sibling_tokens = _sibling_title_tokens(query, ranked_documents)
        query_tokens = frozenset(primary_distinctive_tokens(query))
        keep_title_aligned = query_asks_for_comparison(query)
        keep_vpn_howto = _is_vpn_password_expiry_query(query)
        ranked_documents = [
            group
            for group in ranked_documents
            if max(evidence_confidence(result) for result in group) >= score_floor
            or document_has_competitive_overlap(
                query=query,
                leader=leader,
                candidates=group,
                overlap_ratio=_DOCUMENT_SELECTION_OVERLAP_RATIO,
            )
            or _title_matches_sibling_tokens(group, sibling_tokens)
            or (
                keep_title_aligned
                and _title_query_token_hits(group, query_tokens) > 0
            )
            or (keep_vpn_howto and _group_has_vpn_password_howto(group))
        ]
    max_context_documents = _MAX_CONTEXT_DOCUMENTS
    if any(marker in query for marker in _ACCESS_SCOPE_QUERY_MARKERS) or query_asks_for_comparison(
        query
    ):
        max_context_documents = _MAX_ACCESS_SCOPE_CONTEXT_DOCUMENTS
    limit = min(top_k, max_context_documents)
    if query_asks_for_comparison(query):
        return _prefer_query_titled_documents(
            query,
            ranked_documents,
            limit=limit,
        )
    return ranked_documents[:limit]


def _chunk_distinctive_overlap(
    query: str,
    result: SearchResult,
) -> int:
    tokens = primary_distinctive_tokens(query)
    if not tokens:
        return 0
    text = (
        f"{result.chunk.title}\n{result.chunk.section or ''}\n{result.chunk.content}"
    ).casefold()
    return sum(1 for token in tokens if token.casefold() in text)


def _within_doc_sort_key(query: str, result: SearchResult) -> tuple[int, tuple]:
    # Prefer chunks that carry more distinctive query tokens, then ranking contract.
    return (-_chunk_distinctive_overlap(query, result), ranking_sort_key(result))


def select_chunks_for_documents(
    query: str,
    ranked_documents: Sequence[Sequence[SearchResult]],
    *,
    index_chunks: Sequence[DocumentChunk],
    max_chunks_per_document: int | None,
    canonical_version_results: Callable[
        [Sequence[SearchResult]], list[SearchResult]
    ],
) -> list[SearchResult]:
    is_procedure_query = query_asks_for_procedure_selection(query)
    is_error_branch_query = query_asks_for_error_branch_selection(query)
    default_max_chunks = (
        max_chunks_per_document
        if max_chunks_per_document is not None
        else _MAX_CHUNKS_PER_DOCUMENT
    )
    max_chunks_limit = max_chunks_for_query(
        query=query,
        default_max_chunks=default_max_chunks,
    )
    # Error-branch / procedure monopoly is only safe for single-doc answers.
    allow_procedure_monopoly = (is_procedure_query or is_error_branch_query) and len(
        ranked_documents
    ) <= 1
    # Diversity-first Top-k for comparison and multi-doc procedure/error-branch.
    use_diversity_first = len(ranked_documents) > 1 and (
        query_asks_for_comparison(query)
        or is_procedure_query
        or is_error_branch_query
    )

    if not use_diversity_first:
        selected: list[SearchResult] = []
        for document_results in ranked_documents:
            version_results = canonical_version_results(document_results)
            if allow_procedure_monopoly and len(version_results) >= 1:
                procedure = _procedure_numbered_chunks(
                    version_results,
                    index_chunks=index_chunks,
                    max_chunks_limit=max_chunks_limit,
                )
                if procedure is not None:
                    selected.extend(procedure)
                    continue
            selected.extend(
                sorted(
                    version_results,
                    key=lambda result: _within_doc_sort_key(query, result),
                )[:max_chunks_limit]
            )
        return selected

    # Pass A: one best chunk per document; Pass B: fill remaining per-doc slots.
    first_pass: list[SearchResult] = []
    remaining_by_doc: list[list[SearchResult]] = []
    for document_results in ranked_documents:
        version_results = canonical_version_results(document_results)
        ordered = sorted(
            version_results,
            key=lambda result: _within_doc_sort_key(query, result),
        )
        if not ordered:
            remaining_by_doc.append([])
            continue
        first_pass.append(ordered[0])
        remaining_by_doc.append(ordered[1:max_chunks_limit])

    selected = list(first_pass)
    for extras in remaining_by_doc:
        selected.extend(extras)
    return selected


def _procedure_numbered_chunks(
    version_results: Sequence[SearchResult],
    *,
    index_chunks: Sequence[DocumentChunk],
    max_chunks_limit: int,
) -> list[SearchResult] | None:
    doc_path = version_results[0].chunk.source_path
    doc_id = version_results[0].chunk.document_id
    all_doc_chunks = [
        chunk
        for chunk in index_chunks
        if (doc_id and chunk.document_id == doc_id)
        or (doc_path and chunk.source_path == doc_path)
    ]
    numbered_doc_chunks = [
        chunk for chunk in all_doc_chunks if is_numbered_section(chunk.section)
    ]
    if not numbered_doc_chunks:
        return None
    existing_scores = {
        item.chunk.chunk_id: evidence_confidence(item) for item in version_results
    }
    leader_score = max(evidence_confidence(item) for item in version_results)
    procedure_results: list[SearchResult] = []
    for chunk in numbered_doc_chunks:
        score = existing_scores.get(chunk.chunk_id, leader_score * 0.95)
        procedure_results.append(
            SearchResult(
                chunk=chunk,
                score=score,
                sparse_score=0.0,
                dense_score=0.0,
            )
        )
    procedure_results.sort(key=section_sort_key)
    return procedure_results[:max_chunks_limit]
