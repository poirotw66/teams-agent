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
    logger.info("OpenTelemetry tracing configured for service=%s", service_name)
    return True


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
