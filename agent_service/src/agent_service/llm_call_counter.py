"""Shared LLM call counter used across workflow and knowledge paths."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LlmCallCounter:
    """Tracks how many LLM calls a single request made.

    Callers pass one shared counter when enforcing ``max_llm_calls_per_request``
    across supervisor, extractor, handoff, ticket selection, and knowledge.
    """

    count: int = 0

    def increment(self) -> None:
        self.count += 1
