"""Tests for optional OpenTelemetry helpers."""

from __future__ import annotations

from agent_service.observability import SLO_TARGETS, configure_tracing, start_span


def test_slo_targets_are_documented() -> None:
    assert "agent_turn_p95_latency_seconds" in SLO_TARGETS
    assert "agent_turn_error_rate" in SLO_TARGETS


def test_configure_tracing_disabled_is_noop() -> None:
    assert configure_tracing(service_name="test", enabled=False) is False


def test_start_span_without_otel_is_noop() -> None:
    with start_span("test.span", attributes={"k": "v"}):
        pass
