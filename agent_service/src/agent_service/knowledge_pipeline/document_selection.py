from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_service.documents import DocumentChunk
from agent_service.knowledge_eligibility import is_chunk_generation_eligible
from agent_service.retrieval import SearchResult, is_chunk_visible_to_groups

from .candidate_policy import filter_cross_scenario_chunks
from .document_selection_select import (
    protect_raw_top1,
    rank_documents_for_query,
    select_chunks_for_documents,
)
from .selector import top1_was_displaced

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
    filtered_results = protect_raw_top1(
        query,
        raw_top1,
        filter_cross_scenario_chunks(query, list(results)),
    )
    ranked_documents = rank_documents_for_query(
        query,
        filtered_results,
        document_key=document_key,
        top_k=top_k,
    )
    selected = select_chunks_for_documents(
        query,
        ranked_documents,
        index_chunks=index_chunks,
        max_chunks_per_document=max_chunks_per_document,
        canonical_version_results=canonical_version_results,
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
