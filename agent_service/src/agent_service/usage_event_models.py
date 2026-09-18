"""Usage event and request-cost summary data models."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

logger = logging.getLogger("agent_service.usage_events")

UsageSource = Literal["PROVIDER", "ESTIMATED", "MISSING"]
UsageStatus = Literal["SUCCESS", "FAILED", "TIMEOUT"]


def iso_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def round_cost(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 8)


@dataclass(frozen=True)
class UsageEvent:
    event_id: str
    timestamp: str
    environment: str
    request_id: str
    correlation_id: str
    tenant_id: str | None
    team_id: str | None
    component: str
    provider: str | None
    model: str | None
    knowledge_backend: str | None
    input_tokens: int
    tool_context_tokens: int
    output_tokens: int
    embedding_tokens: int
    llm_call_count: int
    estimated_cost_usd: float | None
    pricing_version: str
    usage_source: UsageSource
    status: UsageStatus
    latency_ms: float

    def to_log_dict(self) -> dict[str, object]:
        billed_input = self.input_tokens + self.tool_context_tokens + self.embedding_tokens
        return {
            "log_type": "usage_event",
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "environment": self.environment,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "team_id": self.team_id,
            "component": self.component,
            "provider": self.provider,
            "model": self.model,
            "knowledge_backend": self.knowledge_backend,
            "input_tokens": self.input_tokens,
            "tool_context_tokens": self.tool_context_tokens,
            "embedding_tokens": self.embedding_tokens,
            "billed_input_tokens": billed_input,
            "output_tokens": self.output_tokens,
            "llm_call_count": self.llm_call_count,
            "estimated_cost_usd": round_cost(self.estimated_cost_usd),
            "pricing_version": self.pricing_version,
            "usage_source": self.usage_source,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass(frozen=True)
class RequestCostSummary:
    request_id: str
    correlation_id: str
    environment: str
    tenant_id: str | None
    team_id: str | None
    outcome: str
    knowledge_backend: str | None
    elapsed_ms: float
    llm_call_count: int
    event_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    embedding_tokens: int
    estimated_cost_usd: float | None
    cost_complete: bool
    usage_coverage: float
    pricing_version: str
    by_model: tuple[dict[str, object], ...] = ()

    def to_log_dict(self) -> dict[str, object]:
        return {
            "log_type": "request_cost",
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "environment": self.environment,
            "tenant_id": self.tenant_id,
            "team_id": self.team_id,
            "outcome": self.outcome,
            "knowledge_backend": self.knowledge_backend,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "llm_call_count": self.llm_call_count,
            "event_count": self.event_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "embedding_tokens": self.embedding_tokens,
            "estimated_cost_usd": round_cost(self.estimated_cost_usd),
            "cost_complete": self.cost_complete,
            "usage_coverage": round(self.usage_coverage, 4),
            "pricing_version": self.pricing_version,
            "models": list(self.by_model),
        }


def log_usage_event(event: UsageEvent) -> None:
    logger.info(
        "usage_event: %s",
        json.dumps(event.to_log_dict(), ensure_ascii=True, sort_keys=True),
    )


def log_request_cost(summary: RequestCostSummary) -> None:
    logger.info(
        "request_cost: %s",
        json.dumps(summary.to_log_dict(), ensure_ascii=True, sort_keys=True),
    )
