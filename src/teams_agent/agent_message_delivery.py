"""Non-streaming answer delivery for Teams message turns."""

from __future__ import annotations

import logging
import time
from typing import Any

from microsoft_teams.api import MessageActivity
from microsoft_teams.apps import ActivityContext

from .agent_gateway import AgentGateway, AgentGatewayError
from .contracts import AgentRequest
from .health_telemetry import AdapterHealthReporter, classify_gateway_status

logger = logging.getLogger(__name__)


async def deliver_gateway_answer(
    *,
    ctx: ActivityContext[MessageActivity],
    request: AgentRequest,
    correlation_id: str,
    started_at: float,
    agent_gateway: AgentGateway,
    adapter_health: AdapterHealthReporter,
    build_activity: Any,
    service_unavailable_message: Any,
) -> None:
    try:
        response = await agent_gateway.answer(request)
    except AgentGatewayError as error:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        status, error_type = classify_gateway_status(error)
        logger.exception("Agent Gateway failed: correlation_id=%s", correlation_id)
        try:
            await ctx.send(service_unavailable_message(correlation_id))
        except Exception as send_error:  # noqa: BLE001 - Teams SDK send failures vary
            status = "FAILED"
            error_type = type(send_error).__name__
        adapter_health.schedule_reply(
            status=status,
            elapsed_ms=elapsed_ms,
            correlation_id=correlation_id,
            channel=request.channel,
            error_type=error_type,
        )
        return

    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    try:
        await ctx.send(build_activity(response, request))
    except Exception as send_error:  # noqa: BLE001 - Teams SDK send failures vary
        adapter_health.schedule_reply(
            status="FAILED",
            elapsed_ms=elapsed_ms,
            correlation_id=correlation_id,
            channel=request.channel,
            error_type=type(send_error).__name__,
        )
        try:
            await ctx.send(service_unavailable_message(correlation_id))
        except Exception:
            logger.exception(
                "Failed to deliver Teams fallback reply: correlation_id=%s",
                correlation_id,
            )
        return
    adapter_health.schedule_reply(
        status="SUCCESS",
        elapsed_ms=elapsed_ms,
        correlation_id=correlation_id,
        channel=request.channel,
    )
