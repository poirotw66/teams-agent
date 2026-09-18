"""Per-request usage event collector."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .file_search_usage import FileSearchUsage
from .file_search_usage import estimate_cost as estimate_file_search_cost
from .usage import active_pricing_version, estimate_cost_usd, normalize_model_name
from .usage_event_extract import infer_provider
from .usage_event_models import (
    UsageEvent,
    UsageSource,
    UsageStatus,
    iso_timestamp,
    log_usage_event,
)


@dataclass
class UsageEventCollector:
    environment: str
    request_id: str
    correlation_id: str
    tenant_id: str | None
    team_id: str | None
    knowledge_backend: str | None
    pricing_version: str = field(default_factory=active_pricing_version)
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

        # Prefer live governed version at emit time so mid-process rate updates stamp correctly.
        pricing_version = active_pricing_version() or self.pricing_version

        event = UsageEvent(
            event_id=str(uuid.uuid4()),
            timestamp=iso_timestamp(),
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
            pricing_version=pricing_version,
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
