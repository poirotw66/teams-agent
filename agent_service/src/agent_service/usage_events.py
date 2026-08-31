"""Structured usage events and request-level cost rollups (Phase 1 observability).

Each model or retrieval call emits one ``UsageEvent`` as structured Cloud Logging.
Events are logged immediately when recorded so partial failures still retain cost
attribution for calls that already completed.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .file_search_usage import FileSearchUsage, estimate_cost as estimate_file_search_cost
from .usage import (
    PRICING_VERSION,
    build_usage_report,
    estimate_cost_usd,
    normalize_model_name,
)

logger = logging.getLogger(__name__)

UsageSource = Literal["PROVIDER", "ESTIMATED", "MISSING"]
UsageStatus = Literal["SUCCESS", "FAILED", "TIMEOUT"]


def _iso_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _round_cost(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 8)


def infer_provider(model: str | None) -> str | None:
    if not model:
        return None
    normalized = normalize_model_name(model).lower()
    if normalized.startswith("gpt-") or normalized.startswith("text-embedding-"):
        return "openai"
    if "gemini" in normalized or normalized.startswith("embedding"):
        return "google"
    return None


def derive_request_outcome(state: Mapping[str, object]) -> str:
    """Classify the request path for cost analysis without logging message text."""
    if state.get("handoff_handled"):
        return "handoff"
    supervisor = state.get("supervisor_decision")
    intent = getattr(supervisor, "intent", None)
    if intent == "GREETING":
        return "greeting"
    if intent in {"NON_IT", "ASSISTANT_META"}:
        return "assistant_scope"

    issue_results = state.get("issue_results") or []
    if any(getattr(result, "resultType", None) == "TICKET_CREATED" for result in issue_results):
        return "ticket_created"
    if any(getattr(result, "resultType", None) == "KNOWLEDGE_ANSWERED" for result in issue_results):
        return "knowledge_hit"
    if any(getattr(result, "resultType", None) == "FAQ_ANSWERED" for result in issue_results):
        return "faq_hit"
    if any(getattr(result, "resultType", None) == "NEED_MORE_INFO" for result in issue_results):
        return "clarification"
    if any(getattr(result, "resultType", None) == "NO_KNOWLEDGE" for result in issue_results):
        return "knowledge_miss"
    if any(getattr(result, "resultType", None) == "TICKET_FOUND" for result in issue_results):
        return "ticket_query"
    return "other"


def extract_provider_usage_from_result(result: object) -> dict[str, int | str] | None:
    """Best-effort token extraction from a single LLM response object."""
    usage_metadata = getattr(result, "usage_metadata", None)
    if usage_metadata is not None:
        input_tokens = _safe_int(getattr(usage_metadata, "input_tokens", None))
        output_tokens = _safe_int(getattr(usage_metadata, "output_tokens", None))
        total_tokens = _safe_int(getattr(usage_metadata, "total_tokens", None))
        if input_tokens or output_tokens or total_tokens:
            return {
                "input_tokens": input_tokens or max(0, total_tokens - output_tokens),
                "output_tokens": output_tokens,
                "usage_source": "PROVIDER",
            }

    response_metadata = getattr(result, "response_metadata", None) or {}
    if isinstance(response_metadata, Mapping):
        token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
        if isinstance(token_usage, Mapping):
            input_tokens = _safe_int(token_usage.get("input_tokens") or token_usage.get("prompt_tokens"))
            output_tokens = _safe_int(
                token_usage.get("output_tokens") or token_usage.get("completion_tokens")
            )
            if input_tokens or output_tokens:
                return {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "usage_source": "PROVIDER",
                }
        model_name = response_metadata.get("model_name") or response_metadata.get("model")
        if isinstance(model_name, str) and model_name.strip():
            return {"model": normalize_model_name(model_name)}

    return None


def extract_file_search_usage_from_result(result: object) -> dict[str, int | str] | None:
    usage_metadata = getattr(result, "usage_metadata", None)
    if usage_metadata is None:
        return None
    prompt = _safe_int(getattr(usage_metadata, "prompt_token_count", None))
    tool_use = _safe_int(getattr(usage_metadata, "tool_use_prompt_token_count", None))
    candidates = _safe_int(getattr(usage_metadata, "candidates_token_count", None))
    if not (prompt or tool_use or candidates):
        return None
    return {
        "input_tokens": prompt,
        "tool_context_tokens": tool_use,
        "output_tokens": candidates,
        "usage_source": "PROVIDER",
    }


def _safe_int(value: object) -> int:
    if value is None:
        return 0
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _event_has_token_data(event: UsageEvent) -> bool:
    return (
        event.usage_source != "MISSING"
        or event.input_tokens > 0
        or event.tool_context_tokens > 0
        or event.output_tokens > 0
        or event.embedding_tokens > 0
    )


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
            "estimated_cost_usd": _round_cost(self.estimated_cost_usd),
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
            "estimated_cost_usd": _round_cost(self.estimated_cost_usd),
            "cost_complete": self.cost_complete,
            "usage_coverage": round(self.usage_coverage, 4),
            "pricing_version": self.pricing_version,
        }


@dataclass
class UsageEventCollector:
    environment: str
    request_id: str
    correlation_id: str
    tenant_id: str | None
    team_id: str | None
    knowledge_backend: str | None
    pricing_version: str = PRICING_VERSION
    _events: list[UsageEvent] = field(default_factory=list, repr=False)

    def events(self) -> tuple[UsageEvent, ...]:
        return tuple(self._events)

    def record(
        self,
        *,
        component: str,
        status: UsageStatus,
        latency_ms: float,
        model: str | None = None,
        provider: str | None = None,
        input_tokens: int = 0,
        tool_context_tokens: int = 0,
        output_tokens: int = 0,
        embedding_tokens: int = 0,
        usage_source: UsageSource = "MISSING",
        llm_call_count: int = 1,
        estimated_cost_override: float | None = None,
    ) -> UsageEvent:
        normalized_model = normalize_model_name(model) if model else None
        if normalized_model == "unknown":
            normalized_model = None
        resolved_provider = provider or infer_provider(normalized_model)
        billed_input = input_tokens + tool_context_tokens + embedding_tokens
        has_token_data = billed_input > 0 or output_tokens > 0

        if estimated_cost_override is not None:
            cost = estimated_cost_override
        elif not has_token_data:
            cost = None
        else:
            cost = estimate_cost_usd(
                normalized_model or "unknown",
                billed_input,
                output_tokens,
            )

        event = UsageEvent(
            event_id=str(uuid.uuid4()),
            timestamp=_iso_timestamp(),
            environment=self.environment,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            tenant_id=self.tenant_id,
            team_id=self.team_id,
            component=component,
            provider=resolved_provider,
            model=normalized_model,
            knowledge_backend=self.knowledge_backend,
            input_tokens=input_tokens,
            tool_context_tokens=tool_context_tokens,
            output_tokens=output_tokens,
            embedding_tokens=embedding_tokens,
            llm_call_count=llm_call_count,
            estimated_cost_usd=cost,
            pricing_version=self.pricing_version,
            usage_source=usage_source,
            status=status,
            latency_ms=latency_ms,
        )
        self._events.append(event)
        log_usage_event(event)
        return event

    def record_file_search(
        self,
        *,
        component: str,
        model: str,
        usage: FileSearchUsage,
        status: UsageStatus,
        latency_ms: float,
    ) -> UsageEvent:
        return self.record(
            component=component,
            status=status,
            latency_ms=latency_ms,
            model=model,
            provider="google",
            input_tokens=usage.prompt_tokens,
            tool_context_tokens=usage.tool_use_prompt_tokens,
            output_tokens=usage.output_tokens,
            usage_source="PROVIDER",
            estimated_cost_override=estimate_file_search_cost(usage, model),
        )


def build_request_cost_summary(
    collector: UsageEventCollector,
    *,
    langchain_usage: Mapping[str, Mapping[str, int]],
    outcome: str,
    elapsed_ms: float,
    llm_call_count: int,
    embedding_tokens: int = 0,
    embedding_model: str | None = None,
) -> RequestCostSummary:
    """Roll up per-call events with LangChain provider totals for the request."""
    report = build_usage_report(
        langchain_usage,
        embedding_tokens=embedding_tokens,
        embedding_model=embedding_model,
    )
    events = collector.events()
    file_search_events = [
        event for event in events if event.component == "gemini_file_search"
    ]
    extra_input = sum(
        event.input_tokens + event.tool_context_tokens + event.embedding_tokens
        for event in file_search_events
    )
    extra_output = sum(event.output_tokens for event in file_search_events)

    input_tokens = report.input_tokens + extra_input
    output_tokens = report.output_tokens + extra_output
    total_tokens = input_tokens + output_tokens

    events_with_tokens = sum(1 for event in events if _event_has_token_data(event))
    usage_coverage = 1.0 if not events else events_with_tokens / len(events)

    event_costs = [
        event.estimated_cost_usd
        for event in events
        if event.estimated_cost_usd is not None
    ]
    event_cost_complete = all(
        event.estimated_cost_usd is not None or not _event_has_token_data(event)
        for event in events
    )

    estimated_cost = report.estimated_cost_usd
    file_search_cost = sum(
        event.estimated_cost_usd
        for event in file_search_events
        if event.estimated_cost_usd is not None
    )
    if estimated_cost is not None and file_search_cost:
        estimated_cost += file_search_cost
    elif estimated_cost is None and event_costs and event_cost_complete:
        estimated_cost = sum(event_costs)

    cost_complete = (
        report.estimated_cost_usd is not None or not langchain_usage
    ) and event_cost_complete
    if file_search_events and any(
        event.estimated_cost_usd is None and _event_has_token_data(event)
        for event in file_search_events
    ):
        cost_complete = False

    return RequestCostSummary(
        request_id=collector.request_id,
        correlation_id=collector.correlation_id,
        environment=collector.environment,
        tenant_id=collector.tenant_id,
        team_id=collector.team_id,
        outcome=outcome,
        knowledge_backend=collector.knowledge_backend,
        elapsed_ms=elapsed_ms,
        llm_call_count=llm_call_count,
        event_count=len(events),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        embedding_tokens=report.embedding_tokens,
        estimated_cost_usd=estimated_cost,
        cost_complete=cost_complete,
        usage_coverage=usage_coverage,
        pricing_version=collector.pricing_version,
    )


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
