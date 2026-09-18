"""Document chunk selection helpers for knowledge pipeline context building."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult, tokenize

from .selector import (
    document_has_competitive_overlap,
    is_numbered_section,
    max_chunks_for_query,
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


def protect_raw_top1(
    query: str,
    raw_top1: SearchResult,
    filtered_results: list[SearchResult],
) -> list[SearchResult]:
    if raw_top1 in filtered_results or raw_top1.score < 0.70:
        return filtered_results
    query_tokens = [token for token in tokenize(query) if len(token) > 1]
    top1_text = f"{raw_top1.chunk.title} {raw_top1.chunk.content}".lower()
    if any(token in top1_text for token in query_tokens):
        filtered_results.insert(0, raw_top1)
    return filtered_results


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

    ranked_documents = sorted(
        by_document.values(),
        key=lambda group: max(result.score for result in group),
        reverse=True,
    )
    if ranked_documents:
        leader = max(ranked_documents[0], key=lambda result: result.score)
        score_floor = leader.score * _DOCUMENT_SELECTION_SCORE_RATIO
        ranked_documents = [
            group
            for group in ranked_documents
            if max(result.score for result in group) >= score_floor
            or document_has_competitive_overlap(
                query=query,
                leader=leader,
                candidates=group,
                overlap_ratio=_DOCUMENT_SELECTION_OVERLAP_RATIO,
            )
        ]
    max_context_documents = _MAX_CONTEXT_DOCUMENTS
    if any(marker in query for marker in _ACCESS_SCOPE_QUERY_MARKERS):
        max_context_documents = _MAX_ACCESS_SCOPE_CONTEXT_DOCUMENTS
    return ranked_documents[: min(top_k, max_context_documents)]


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
    selected: list[SearchResult] = []
    for document_results in ranked_documents:
        version_results = canonical_version_results(document_results)
        if (is_procedure_query or is_error_branch_query) and len(version_results) >= 1:
            procedure = _procedure_numbered_chunks(
                version_results,
                index_chunks=index_chunks,
                max_chunks_limit=max_chunks_limit,
            )
            if procedure is not None:
                selected.extend(procedure)
                continue
        selected.extend(
            sorted(version_results, key=lambda result: result.score, reverse=True)[
                :max_chunks_limit
            ]
        )
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
    existing_scores = {item.chunk.chunk_id: item.score for item in version_results}
    leader_score = max(item.score for item in version_results)
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
