"""REQ-024 Teams Adapter health reporter unit tests."""

from __future__ import annotations

import pytest

from teams_agent.agent_gateway import AgentGateway, AgentGatewayTimeoutError
from teams_agent.health_telemetry import AdapterHealthReporter, classify_gateway_status
from teams_agent.settings import AgentSettings


def test_classify_gateway_timeout() -> None:
    status, error_type = classify_gateway_status(
        AgentGatewayTimeoutError("Agent API request timed out.")
    )
    assert status == "TIMEOUT"
    assert error_type == "AgentGatewayTimeoutError"


@pytest.mark.asyncio
async def test_adapter_health_reporter_posts_reply_sample() -> None:
    captured: dict = {}

    async def fake_transport(url, payload, headers, timeout):
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {"accepted": True}

    settings = AgentSettings(
        mode="api",
        api_url="https://agent.example/agent/chat",
        api_token="token",
        api_auth_mode="service_token",
    )
    gateway = AgentGateway(settings, transport=fake_transport)
    reporter = AdapterHealthReporter(settings, gateway)
    await reporter.report_reply(
        status="FAILED",
        elapsed_ms=123.4,
        correlation_id="corr-1",
        channel="msteams",
        error_type="SendError",
    )
    assert captured["url"] == "https://agent.example/agent/ops/health-telemetry"
    assert captured["payload"] == {
        "component": "teams_adapter",
        "status": "FAILED",
        "elapsedMs": 123.4,
        "correlationId": "corr-1",
        "attributionScope": "ADAPTER_REPLY",
        "channel": "msteams",
        "errorType": "SendError",
    }
    assert captured["headers"]["Authorization"] == "Bearer token"
