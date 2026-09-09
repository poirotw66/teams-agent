"""Best-effort Teams Adapter reply health telemetry (REQ-024)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .agent_gateway import AgentGateway, AgentGatewayError, AgentGatewayTimeoutError
from .settings import AgentSettings

logger = logging.getLogger(__name__)


def classify_gateway_status(error: BaseException) -> tuple[str, str]:
    """Map gateway failures to health status + errorType."""
    if isinstance(error, AgentGatewayTimeoutError):
        return "TIMEOUT", type(error).__name__
    cause = error.__cause__
    if isinstance(error, TimeoutError) or isinstance(cause, TimeoutError):
        return "TIMEOUT", type(error).__name__
    if isinstance(error, AgentGatewayError):
        message = str(error).lower()
        if "timeout" in message:
            return "TIMEOUT", type(error).__name__
    return "FAILED", type(error).__name__


class AdapterHealthReporter:
    """POST Adapter reply samples to Agent Service ops ingest."""

    def __init__(
        self,
        settings: AgentSettings,
        gateway: AgentGateway,
    ) -> None:
        self._settings = settings
        self._gateway = gateway

    async def report_reply(
        self,
        *,
        status: str,
        elapsed_ms: float,
        correlation_id: str,
        channel: str | None = None,
        error_type: str | None = None,
    ) -> None:
        if self._settings.mode == "echo":
            return
        url = self._settings.resolved_health_telemetry_url
        if not url:
            return
        payload: dict[str, Any] = {
            "component": "teams_adapter",
            "status": status,
            "elapsedMs": round(elapsed_ms, 1),
            "correlationId": correlation_id,
            "attributionScope": "ADAPTER_REPLY",
        }
        if channel:
            payload["channel"] = channel
        if error_type:
            payload["errorType"] = error_type
        try:
            await self._gateway.post_json(
                url,
                payload,
                timeout_seconds=min(self._settings.api_timeout_seconds, 5.0),
            )
        except Exception:
            logger.warning(
                "Failed to report adapter health telemetry: correlation_id=%s status=%s",
                correlation_id,
                status,
                exc_info=True,
            )

    def schedule_reply(self, **kwargs: Any) -> None:
        """Fire-and-forget reporting that never blocks the Teams reply path."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.report_reply(**kwargs))
