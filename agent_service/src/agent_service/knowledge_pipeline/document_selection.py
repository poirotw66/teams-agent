"""Document candidate injection and context-chunk selection (pure policies)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_service.documents import DocumentChunk
from agent_service.knowledge_eligibility import is_chunk_generation_eligible
from agent_service.retrieval import SearchResult, is_chunk_visible_to_groups, tokenize

from .candidate_policy import filter_cross_scenario_chunks
from .selector import (
    document_has_competitive_overlap,
    is_numbered_section,
    max_chunks_for_query,
    query_asks_for_error_branch_selection,
    query_asks_for_procedure_selection,
    section_sort_key,
    top1_was_displaced,
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

_ENTERPRISE_APP_QUERY_TERMS: tuple[str, ...] = (
    "企業 App",
    "企業App",
    "企業級APP",
    "企業級 App",
    "來源所述的企業",
)
_ENTERPRISE_TRUST_MARKERS: tuple[str, ...] = (
    "企業級APP",
    "企業級 App",
    "CATHAY LIFE",
)


def inject_enterprise_app_evidence(
    query: str,
    results: Sequence[SearchResult],
    *,
    index_chunks: Sequence[DocumentChunk],
    groups: set[str],
    environment: str,
) -> list[SearchResult]:
    """Ensure enterprise-app trust docs enter and lead the candidate pool.

    Hybrid retrieval often ranks AD/Outlook ahead of the portal note that
    actually describes 企業級APP / CATHAY LIFE verification.

    Injection must never reintroduce chunks that Hybrid search already
    excluded for ACL or generation eligibility.
    """
    if not any(term in query for term in _ENTERPRISE_APP_QUERY_TERMS):
        return list(results)

    def _is_enterprise_trust_chunk(chunk: DocumentChunk) -> bool:
        blob = f"{chunk.title}\n{chunk.content}"
        return any(marker in blob for marker in _ENTERPRISE_TRUST_MARKERS)

    def _is_injectable(chunk: DocumentChunk) -> bool:
        return is_chunk_visible_to_groups(
            chunk, groups
        ) and is_chunk_generation_eligible(chunk, environment=environment)

    boosted: list[SearchResult] = []
    seen_ids: set[str] = set()
    for result in results:
        seen_ids.add(result.chunk.chunk_id)
        if _is_enterprise_trust_chunk(result.chunk):
            boosted.append(
                SearchResult(
                    chunk=result.chunk,
                    score=max(result.score, 0.92),
                    sparse_score=result.sparse_score,
                    dense_score=result.dense_score,
                )
            )
        else:
            boosted.append(result)

    for chunk in index_chunks:
        if chunk.chunk_id in seen_ids:
            continue
        if not _is_injectable(chunk):
            continue
        if _is_enterprise_trust_chunk(chunk):
            boosted.append(
                SearchResult(
                    chunk=chunk,
                    score=0.92,
                    sparse_score=0.92,
                    dense_score=0.0,
                )
            )
            seen_ids.add(chunk.chunk_id)

    return sorted(boosted, key=lambda item: item.score, reverse=True)


def canonical_version_results(results: Sequence[SearchResult]) -> list[SearchResult]:
    numbered = [result for result in results if result.chunk.version_number is not None]
    if numbered:
        latest = max(result.chunk.version_number or 0 for result in numbered)
        return [result for result in results if result.chunk.version_number == latest]
    leading_version = results[0].chunk.version_id if results else None
    if leading_version is None:
        return list(results)
    return [result for result in results if result.chunk.version_id == leading_version]


def select_document_chunks(
    query: str,
    results: Sequence[SearchResult],
    *,
    document_key: Callable[[SearchResult], str],
    index_chunks: Sequence[DocumentChunk],
    top_k: int,
    max_chunks_per_document: int | None = None,
) -> tuple[list[SearchResult], bool]:
    if not results:
        return ([], False)

    raw_top1 = results[0]
    filtered_results = filter_cross_scenario_chunks(query, list(results))

    # Raw top-1 protection: if raw top-1 had high confidence (score >= 0.70)
    # and matched query terms, do not let heuristic filtering drop it
    if raw_top1 not in filtered_results and raw_top1.score >= 0.70:
        query_tokens = [token for token in tokenize(query) if len(token) > 1]
        top1_text = f"{raw_top1.chunk.title} {raw_top1.chunk.content}".lower()
        if any(token in top1_text for token in query_tokens):
            filtered_results.insert(0, raw_top1)

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
    ranked_documents = ranked_documents[: min(top_k, max_context_documents)]

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
            if numbered_doc_chunks:
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
                selected.extend(procedure_results[:max_chunks_limit])
                continue

        selected.extend(
            sorted(
                version_results,
                key=lambda result: result.score,
                reverse=True,
            )[:max_chunks_limit]
        )

    displaced_top1 = top1_was_displaced(
        raw_top1=raw_top1,
        selected=selected,
        document_key=document_key,
    )
    return (selected, displaced_top1)


__all__ = [
    "canonical_version_results",
    "inject_enterprise_app_evidence",
    "select_document_chunks",
]
