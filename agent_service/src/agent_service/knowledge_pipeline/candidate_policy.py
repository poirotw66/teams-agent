"""ACL / scenario isolation helpers that are pure (no index I/O)."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult

from .candidate_policy_filters import (
    apply_audience_isolation,
    apply_enterprise_app_boost,
    apply_platform_isolation,
    apply_product_isolation,
    apply_scenario_isolation,
)
from .candidate_policy_intents import detect_query_intent_flags

_NON_PRODUCTION_TITLE_MARKERS: tuple[str, ...] = (
    "[UX-AUDIT]",
    "[TEST]",
    "UX-AUDIT",
)


def is_non_production_knowledge_chunk(chunk: DocumentChunk) -> bool:
    title = chunk.title or ""
    return any(marker in title for marker in _NON_PRODUCTION_TITLE_MARKERS)


def filter_cross_scenario_chunks(
    query: str,
    results: list[SearchResult],
) -> list[SearchResult]:
    """Drop cross-scenario / cross-audience noise from retrieval candidates."""
    if not results:
        return results

    results = [
        result for result in results if not is_non_production_knowledge_chunk(result.chunk)
    ]
    if not results:
        return results

    intent = detect_query_intent_flags(query)
    results = apply_scenario_isolation(results, intent.target_scenario)
    results = apply_audience_isolation(results, intent)
    results = apply_product_isolation(results, intent)
    results = apply_platform_isolation(results, intent)
    return apply_enterprise_app_boost(results, intent)
