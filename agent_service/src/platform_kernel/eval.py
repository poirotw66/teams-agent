"""Eval observation contract shared by Agent harnesses and Backoffice scorers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FlowObservation:
    route: str
    label: str
    refused_injection: bool
    detail: str
    used_template_chars: int
    reply_text: str = ""
    observed_behaviors: frozenset[str] = field(default_factory=frozenset)
    model_id_used: str | None = None
    llm_call_count: int | None = None
    latency_ms: float | None = None
