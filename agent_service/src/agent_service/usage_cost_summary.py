"""Request-level cost rollups from per-call usage events."""

from __future__ import annotations

from collections.abc import Mapping

from .usage import active_pricing_version, build_usage_report
from .usage_event_collector import UsageEventCollector
from .usage_event_models import RequestCostSummary, UsageEvent


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


def event_has_token_data(event: UsageEvent) -> bool:
    return (
        event.usage_source != "MISSING"
        or event.input_tokens > 0
        or event.tool_context_tokens > 0
        or event.output_tokens > 0
        or event.embedding_tokens > 0
    )


def _file_search_model_rows(
    file_search_events: list[UsageEvent],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for event in file_search_events:
        if not event.model:
            continue
        billed = event.input_tokens + event.tool_context_tokens + event.embedding_tokens
        rows.append(
            {
                "model": event.model,
                "provider": event.provider,
                "inputTokens": billed,
                "outputTokens": event.output_tokens,
                "totalTokens": billed + event.output_tokens,
                "embeddingTokens": event.embedding_tokens,
                "estimatedCostUsd": event.estimated_cost_usd,
                "llmCallCount": event.llm_call_count,
            }
        )
    return rows


def _resolve_estimated_cost(
    *,
    report_cost: float | None,
    file_search_events: list[UsageEvent],
    events: tuple[UsageEvent, ...],
    event_cost_complete: bool,
) -> float | None:
    event_costs = [
        event.estimated_cost_usd for event in events if event.estimated_cost_usd is not None
    ]
    file_search_cost = sum(
        event.estimated_cost_usd
        for event in file_search_events
        if event.estimated_cost_usd is not None
    )
    estimated_cost = report_cost
    if estimated_cost is not None and file_search_cost:
        estimated_cost += file_search_cost
    elif estimated_cost is None and event_costs and event_cost_complete:
        estimated_cost = sum(event_costs)
    return estimated_cost


def _cost_complete(
    *,
    report_cost: float | None,
    langchain_usage: Mapping[str, Mapping[str, int]],
    event_cost_complete: bool,
    file_search_events: list[UsageEvent],
) -> bool:
    has_langchain_tokens = any(
        any(
            int(metadata.get(field, 0) or 0) > 0
            for field in ("input_tokens", "output_tokens", "total_tokens")
        )
        for metadata in langchain_usage.values()
    )
    complete = (report_cost is not None or not has_langchain_tokens) and event_cost_complete
    if file_search_events and any(
        event.estimated_cost_usd is None and event_has_token_data(event)
        for event in file_search_events
    ):
        return False
    return complete


def _report_model_rows(report: object) -> list[dict[str, object]]:
    return [
        {
            "model": item.model,
            "inputTokens": item.input_tokens,
            "outputTokens": item.output_tokens,
            "totalTokens": item.total_tokens,
            "estimatedCostUsd": item.estimated_cost_usd,
            "llmCallCount": 1 if item.total_tokens or item.estimated_cost_usd else 0,
        }
        for item in report.by_model  # type: ignore[attr-defined]
    ]


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
    file_search_events = [event for event in events if event.component == "gemini_file_search"]
    extra_input = sum(
        event.input_tokens + event.tool_context_tokens + event.embedding_tokens
        for event in file_search_events
    )
    extra_output = sum(event.output_tokens for event in file_search_events)
    input_tokens = report.input_tokens + extra_input
    output_tokens = report.output_tokens + extra_output
    events_with_tokens = sum(1 for event in events if event_has_token_data(event))
    usage_coverage = 1.0 if not events else events_with_tokens / len(events)
    event_cost_complete = all(
        event.estimated_cost_usd is not None or not event_has_token_data(event) for event in events
    )
    estimated_cost = _resolve_estimated_cost(
        report_cost=report.estimated_cost_usd,
        file_search_events=file_search_events,
        events=events,
        event_cost_complete=event_cost_complete,
    )
    by_model = _report_model_rows(report) + _file_search_model_rows(file_search_events)
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
        total_tokens=input_tokens + output_tokens,
        embedding_tokens=report.embedding_tokens,
        estimated_cost_usd=estimated_cost,
        cost_complete=_cost_complete(
            report_cost=report.estimated_cost_usd,
            langchain_usage=langchain_usage,
            event_cost_complete=event_cost_complete,
            file_search_events=file_search_events,
        ),
        usage_coverage=usage_coverage,
        pricing_version=active_pricing_version() or collector.pricing_version,
        by_model=tuple(by_model),
    )
