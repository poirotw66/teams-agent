"""OpenTelemetry foundations (docs/0919-arch.md P2).

Optional dependency: install ``teams-agent-rag-service[otel]``. When the SDK
is absent or tracing is disabled, helpers are no-ops so runtime stays lean.
"""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager, nullcontext
from typing import Any

logger = logging.getLogger(__name__)

# Production SLO targets (review gates; not auto-enforced yet).
SLO_TARGETS: dict[str, str] = {
    "agent_turn_p95_latency_seconds": "8",
    "agent_turn_error_rate": "0.01",
    "knowledge_retrieval_p95_latency_seconds": "3",
    "adapter_inbound_availability": "0.995",
}


def configure_tracing(
    *,
    service_name: str,
    enabled: bool = False,
    exporter_endpoint: str | None = None,
) -> bool:
    """Initialize a TracerProvider when OTel is installed and enabled.

    Returns True when a real provider was configured.
    """
    if not enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        logger.warning(
            "OTEL enabled but opentelemetry packages missing; install [otel] extra."
        )
        return False

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if exporter_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=exporter_endpoint))
            )
        except ImportError:
            logger.warning("OTLP exporter unavailable; falling back to console exporter.")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _configure_metrics(
        service_name=service_name,
        exporter_endpoint=exporter_endpoint,
    )
    logger.info("OpenTelemetry tracing configured for service=%s", service_name)
    return True


def _configure_metrics(*, service_name: str, exporter_endpoint: str | None) -> bool:
    """Best-effort MeterProvider so RAG counters can export beyond process memory."""
    try:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
    except ImportError:
        return False

    reader = None
    if exporter_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )

            reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=exporter_endpoint)
            )
        except ImportError:
            logger.warning("OTLP metric exporter unavailable; metrics stay process-local.")
            return False
    else:
        try:
            from opentelemetry.sdk.metrics.export import ConsoleMetricExporter

            reader = PeriodicExportingMetricReader(ConsoleMetricExporter())
        except ImportError:
            return False

    resource = Resource.create({"service.name": service_name})
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    logger.info("OpenTelemetry metrics configured for service=%s", service_name)
    return True


def record_metric_counter(
    name: str,
    amount: float = 1.0,
    *,
    attributes: dict[str, str | int | float | bool] | None = None,
) -> None:
    """Increment an OTel counter when a MeterProvider is configured; else no-op."""
    if amount == 0:
        return
    try:
        from opentelemetry import metrics
    except ImportError:
        return
    try:
        meter = metrics.get_meter("teams-agent.rag")
        counter = meter.create_counter(name)
        if attributes:
            counter.add(amount, attributes=attributes)
        else:
            counter.add(amount)
    except Exception:  # noqa: BLE001 - metrics must never break request path
        logger.debug("Failed to record OTel counter %s", name, exc_info=True)


def record_metric_histogram(
    name: str,
    value: float,
    *,
    attributes: dict[str, str | int | float | bool] | None = None,
) -> None:
    """Record an OTel histogram sample when metrics are configured; else no-op."""
    try:
        from opentelemetry import metrics
    except ImportError:
        return
    try:
        meter = metrics.get_meter("teams-agent.rag")
        histogram = meter.create_histogram(name)
        if attributes:
            histogram.record(value, attributes=attributes)
        else:
            histogram.record(value)
    except Exception:  # noqa: BLE001 - metrics must never break request path
        logger.debug("Failed to record OTel histogram %s", name, exc_info=True)


# Named counters from the production-optimization observability contract.
METRIC_TURN_PLANNER_SELECTED = "agent_turn_planner_selected_total"
METRIC_TURN_PLANNER_FALLBACK = "agent_turn_planner_fallback_total"
METRIC_LLM_BUDGET_DENIED = "agent_llm_budget_denied_total"
METRIC_LLM_BUDGET_EVENT = "agent_llm_budget_event_total"
METRIC_ANSWER_ESCALATION = "rag_answer_escalation_total"
METRIC_ANSWER_ESCALATION_SUCCESS = "rag_answer_escalation_success_total"
METRIC_EVIDENCE_DROP = "rag_evidence_drop_total"
METRIC_CITATION_PRUNED = "rag_citation_pruned_total"
METRIC_LEGACY_RAG_AGENT = "legacy_rag_agent_invocation_total"
METRIC_REQUEST_LATENCY_MS = "agent_request_latency_ms"
METRIC_FIRST_STAGE_LATENCY_MS = "agent_first_stage_latency_ms"
METRIC_LLM_SEMAPHORE_WAIT_MS = "agent_llm_semaphore_wait_ms"
METRIC_RETRIEVAL_LATENCY_MS = "rag_retrieval_latency_ms"
METRIC_RELEVANCE_LATENCY_MS = "rag_relevance_latency_ms"
METRIC_REWRITE_LATENCY_MS = "rag_rewrite_latency_ms"
METRIC_GENERATION_LATENCY_MS = "rag_generation_latency_ms"
METRIC_CLAIM_REPAIR_LATENCY_MS = "rag_claim_repair_latency_ms"
METRIC_TOTAL_LATENCY_MS = "rag_total_latency_ms"


def start_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> AbstractContextManager[Any]:
    """Start a span, or nullcontext when tracing is unavailable."""
    try:
        from opentelemetry import trace
    except ImportError:
        return nullcontext()

    tracer = trace.get_tracer("teams-agent")
    span_cm = tracer.start_as_current_span(name)
    if not attributes:
        return span_cm

    class _AttributedSpan:
        def __enter__(self) -> Any:
            self._span = span_cm.__enter__()
            for key, value in attributes.items():
                if value is not None:
                    self._span.set_attribute(key, value)
            return self._span

        def __exit__(self, *exc: object) -> bool | None:
            return span_cm.__exit__(*exc)

    return _AttributedSpan()
