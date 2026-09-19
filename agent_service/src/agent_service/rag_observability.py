"""RAG v2 retrieval observability helpers (spec §36–§38).

Counters are process-local and optional; OTel spans reuse ``start_span``.
Never attach full user queries or document bodies to span attributes.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from .observability import SLO_TARGETS, start_span

# Extend shared SLO targets with RAG v2 retrieval budgets.
SLO_TARGETS.update(
    {
        "rag_retrieval_p95_latency_ms": "3000",
        "rag_rerank_p95_latency_ms": "700",
    }
)

_LOCK = threading.Lock()
_COUNTERS: dict[str, float] = {
    "rag_reranker_timeout_total": 0.0,
    "rag_reranker_failure_total": 0.0,
    "rag_no_answer_total": 0.0,
    "rag_retrieval_cache_hits": 0.0,
    "rag_retrieval_cache_misses": 0.0,
    "rag_query_tier_trivial": 0.0,
    "rag_query_tier_standard": 0.0,
    "rag_query_tier_hard": 0.0,
}


def increment_counter(name: str, amount: float = 1.0) -> None:
    with _LOCK:
        _COUNTERS[name] = _COUNTERS.get(name, 0.0) + amount


def snapshot_counters() -> dict[str, float]:
    with _LOCK:
        return dict(_COUNTERS)


def reset_counters() -> None:
    with _LOCK:
        for key in list(_COUNTERS):
            _COUNTERS[key] = 0.0


def record_query_tier(tier: str | None) -> None:
    if not tier:
        return
    key = f"rag_query_tier_{tier.lower()}"
    increment_counter(key)


def record_cache_hit(hit: bool) -> None:
    increment_counter("rag_retrieval_cache_hits" if hit else "rag_retrieval_cache_misses")


@contextmanager
def rag_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[dict[str, float]]:
    """Start ``rag.*`` span and yield a timing dict updated by the caller."""
    timing: dict[str, float] = {"started": time.perf_counter()}
    safe_attrs = {
        key: value
        for key, value in (attributes or {}).items()
        if key
        not in {
            "query",
            "user_query",
            "document_body",
            "content",
            "answer",
        }
    }
    with start_span(name, attributes=safe_attrs):
        try:
            yield timing
        finally:
            timing["elapsedMs"] = round((time.perf_counter() - timing["started"]) * 1000, 1)


def retrieval_span(
    *,
    fusion_mode: str,
    release_id: str,
    cache_hit: bool | None = None,
) -> AbstractContextManager[dict[str, float]]:
    attrs: dict[str, Any] = {
        "fusion_mode": fusion_mode,
        "release_id": release_id or "",
    }
    if cache_hit is not None:
        attrs["cache_hit"] = cache_hit
    return rag_span("rag.retrieve", attributes=attrs)


def rerank_span(
    *,
    reranker_model: str | None,
    candidate_count: int,
    query_tier: str | None = None,
) -> AbstractContextManager[dict[str, float]]:
    return rag_span(
        "rag.rerank",
        attributes={
            "reranker_model": reranker_model or "noop",
            "candidate_count": candidate_count,
            "query_tier": query_tier or "",
        },
    )


__all__ = [
    "increment_counter",
    "rag_span",
    "record_cache_hit",
    "record_query_tier",
    "rerank_span",
    "reset_counters",
    "retrieval_span",
    "snapshot_counters",
]
