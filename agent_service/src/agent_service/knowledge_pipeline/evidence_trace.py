"""Evaluation-channel evidence progression without document bodies or user text."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

DropStage = Literal[
    "CANDIDATE_FILTER",
    "DOCUMENT_SELECTION",
    "VERSION_FILTER",
    "DIVERSITY_LIMIT",
    "EVIDENCE_EXPANSION",
    "CONTEXT_PACKING",
    "GENERATION",
    "CITATION_PRUNING",
]
DropReason = Literal[
    "TOKEN_BUDGET",
    "SOURCE_ROLE",
    "NOT_CITED",
    "ACL",
    "VERSION",
    "DIVERSITY",
    "IRRELEVANT",
]


def build_evidence_progression(
    *,
    candidate_chunk_ids: Sequence[str],
    post_selection_chunk_ids: Sequence[str],
    bundle_chunk_ids: Sequence[str],
    generator_context_chunk_ids: Sequence[str],
    cited_chunk_ids: Sequence[str],
) -> dict[str, object]:
    """Record chunk-id progression and the stage where each id was dropped."""
    dropped: list[dict[str, str]] = []
    stages = (
        (set(candidate_chunk_ids), set(post_selection_chunk_ids), "DOCUMENT_SELECTION", "IRRELEVANT"),
        (set(post_selection_chunk_ids), set(bundle_chunk_ids), "EVIDENCE_EXPANSION", "SOURCE_ROLE"),
        (set(bundle_chunk_ids), set(generator_context_chunk_ids), "CONTEXT_PACKING", "TOKEN_BUDGET"),
        (set(generator_context_chunk_ids), set(cited_chunk_ids), "CITATION_PRUNING", "NOT_CITED"),
    )
    seen: set[str] = set()
    for before, after, stage, reason in stages:
        for chunk_id in before - after:
            if not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            dropped.append({"chunkId": chunk_id, "stage": stage, "reason": reason})
    return {
        "candidateChunkIds": list(candidate_chunk_ids),
        "postSelectionChunkIds": list(post_selection_chunk_ids),
        "bundleChunkIds": list(bundle_chunk_ids),
        "generatorContextChunkIds": list(generator_context_chunk_ids),
        "citedChunkIds": list(cited_chunk_ids),
        "droppedEvidence": dropped,
    }


def chunk_ids(items: Iterable[object], *, attr: str = "chunk_id") -> list[str]:
    ids: list[str] = []
    for item in items:
        chunk = getattr(item, "chunk", item)
        value = getattr(chunk, attr, None) or getattr(chunk, "chunkId", None)
        if value:
            ids.append(str(value))
    return ids


def progression_for_retrieval(
    *,
    record: bool,
    cited_chunk_ids: Sequence[str],
    selected_chunk_ids: Sequence[str],
    candidate_chunk_ids: Sequence[str],
    generator_context_chunk_ids: Sequence[str],
) -> dict[str, object] | None:
    """Build progression only when the evaluation channel requests it."""
    if not record:
        return None
    selected = list(selected_chunk_ids)
    candidates = list(candidate_chunk_ids) or selected
    context_ids = list(generator_context_chunk_ids) or selected
    return build_evidence_progression(
        candidate_chunk_ids=candidates,
        post_selection_chunk_ids=selected,
        bundle_chunk_ids=selected,
        generator_context_chunk_ids=context_ids,
        cited_chunk_ids=list(cited_chunk_ids),
    )


def attach_hybrid_result_trace(
    result: object,
    state: object,
    *,
    execution_context: object | None,
    fallback_path: str,
    terminal_reason: str | None,
) -> object:
    """Attach retrieval + answer-escalation trace fields for HybridKnowledgeService."""
    from agent_service.knowledge_pipeline.trace import (
        attach_retrieval_trace,
        current_answer_trace,
    )

    selected_backend = "HYBRID"
    record = False
    if execution_context is not None:
        selected = getattr(execution_context, "selected_knowledge_backend", None)
        if selected:
            selected_backend = str(selected)
        record = bool(
            getattr(execution_context, "evaluation_override", lambda _k: None)(
                "record_evidence_progression"
            )
        ) or str(getattr(execution_context, "correlation_id", "")).startswith("rag-eval")

    answer_trace = current_answer_trace() or {}
    results = list(getattr(state, "results", []) or [])
    raw_results = list(getattr(state, "raw_results", []) or [])
    progression = progression_for_retrieval(
        record=record,
        cited_chunk_ids=[
            source.chunkId
            for source in getattr(result, "sources", []) or []
            if getattr(source, "chunkId", None)
        ],
        selected_chunk_ids=[
            item.chunk.chunk_id for item in results if getattr(item.chunk, "chunk_id", None)
        ],
        candidate_chunk_ids=list(getattr(state, "candidate_chunk_ids", []) or [])
        or [item.chunk.chunk_id for item in raw_results if getattr(item.chunk, "chunk_id", None)],
        generator_context_chunk_ids=list(
            getattr(state, "generator_context_chunk_ids", []) or []
        ),
    )

    def _trace_str(key: str) -> str | None:
        value = answer_trace.get(key)
        return value if isinstance(value, str) else None

    return attach_retrieval_trace(
        result,  # type: ignore[arg-type]
        raw_user_utterance=getattr(state, "raw_user_utterance", ""),
        resolved_issue_query=getattr(state, "resolved_issue_query", ""),
        search_query=getattr(state, "search_query", ""),
        facet_queries=list(getattr(state, "facet_queries", []) or []),
        selected_backend=selected_backend,
        attempts=list(getattr(state, "trace_attempts", []) or []),
        stage_timings_ms=dict(getattr(state, "stage_timings_ms", {}) or {}),
        fallback_path=fallback_path,
        terminal_reason=terminal_reason,
        query_tier=getattr(state, "query_tier", None),
        evidence_progression=progression,
        answer_model=_trace_str("answerModel"),
        answer_escalated=bool(answer_trace.get("answerEscalated")),
        answer_escalation_model=_trace_str("answerEscalationModel"),
        answer_escalation_reason=_trace_str("answerEscalationReason"),
        answer_attempt_count=int(answer_trace.get("answerAttemptCount") or 1),
    )


__all__ = [
    "DropReason",
    "DropStage",
    "attach_hybrid_result_trace",
    "build_evidence_progression",
    "chunk_ids",
    "progression_for_retrieval",
]
