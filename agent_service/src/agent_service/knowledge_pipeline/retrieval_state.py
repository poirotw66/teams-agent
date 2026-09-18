"""Retrieval-state dataclass shared by HybridKnowledgeService stages."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_service.contracts import RetrievalAttempt
from agent_service.retrieval import SearchResult


@dataclass(frozen=True)
class RetrievalState:
    raw_user_utterance: str
    resolved_issue_query: str
    search_query: str
    facet_queries: tuple[str, ...] = ()
    results: list[SearchResult] = field(default_factory=list)
    raw_results: list[SearchResult] = field(default_factory=list)
    filter_displaced_top1: bool = False
    trace_attempts: list[RetrievalAttempt] = field(default_factory=list)
    attempt: int = 0
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    query_tier: str | None = None
    enable_generation_retries: bool = True


__all__ = ["RetrievalState"]
