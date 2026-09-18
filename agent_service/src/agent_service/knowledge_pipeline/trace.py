"""RetrievalTrace and RetrievalAttempt assembly helpers."""

from __future__ import annotations

from collections.abc import Sequence

from agent_service.contracts import (
    KnowledgeResult,
    RetrievalAttempt,
    RetrievalCandidate,
    RetrievalTrace,
)
from agent_service.retrieval import SearchResult


def build_retrieval_attempt(
    search_query: str,
    result_set: Sequence[SearchResult],
    selected_chunk_ids: set[str],
) -> RetrievalAttempt:
    return RetrievalAttempt(
        searchQuery=search_query,
        candidates=[
            RetrievalCandidate(
                rank=rank,
                chunkId=result.chunk.chunk_id,
                documentId=result.chunk.document_id,
                canonicalSourceId=result.chunk.document_id,
                title=result.chunk.title,
                score=result.score,
                sparseScore=result.sparse_score,
                denseScore=result.dense_score,
                scoreOrigin="HYBRID",
                selectedForContext=(result.chunk.chunk_id in selected_chunk_ids),
                rejectionReason=(
                    None
                    if result.chunk.chunk_id in selected_chunk_ids
                    else "DOCUMENT_OR_CHUNK_LIMIT"
                ),
            )
            for rank, result in enumerate(result_set, start=1)
        ],
    )


def attach_retrieval_trace(
    result: KnowledgeResult,
    *,
    raw_user_utterance: str,
    resolved_issue_query: str,
    search_query: str,
    facet_queries: Sequence[str],
    selected_backend: str | None,
    attempts: list[RetrievalAttempt],
    stage_timings_ms: dict[str, float],
    fallback_path: str,
    terminal_reason: str | None,
    actual_backend: str = "HYBRID",
    query_tier: str | None = None,
) -> KnowledgeResult:
    """Attach a ``RetrievalTrace`` and terminal reason onto a knowledge result."""
    trace = RetrievalTrace(
        rawUserUtterance=raw_user_utterance,
        resolvedIssueQuery=resolved_issue_query,
        searchQuery=search_query,
        facetQueries=list(facet_queries),
        selectedBackend=selected_backend or actual_backend,
        actualBackend=actual_backend,
        attempts=attempts,
        selectedChunkIds=[source.chunkId for source in result.sources if source.chunkId],
        answerability=result.answerability,
        claims=result.claims,
        policyAdvisories=result.policyAdvisories,
        unknowns=result.unknowns,
        fallbackPath=fallback_path,
        terminalReason=terminal_reason,
        stageTimingsMs=dict(stage_timings_ms),
        queryTier=query_tier,
    )
    return result.model_copy(
        update={
            "terminalReason": terminal_reason,
            "retrievalTrace": trace,
        }
    )
