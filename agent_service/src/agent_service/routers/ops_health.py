"""Adapter-facing health telemetry ingest for REQ-024 producers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Literal

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field

from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.policy_runtime import active_retention_days


class HealthTelemetryPayload(BaseModel):
    component: str = Field(min_length=1, max_length=128)
    status: Literal["SUCCESS", "FAILED", "TIMEOUT"] = "SUCCESS"
    elapsedMs: float | None = Field(default=None, ge=0)
    correlationId: str | None = Field(default=None, max_length=256)
    attributionScope: Literal[
        "ADAPTER_REPLY",
        "HEALTH_TELEMETRY",
        "RETRIEVAL_INDEX",
    ] = "ADAPTER_REPLY"
    errorType: str | None = Field(default=None, max_length=128)
    channel: str | None = Field(default=None, max_length=64)


def register_ops_health_routes(
    app: FastAPI,
    *,
    authorize: Callable[..., None],
) -> None:
    @app.post(
        "/agent/ops/health-telemetry",
        dependencies=[Depends(authorize)],
    )
    async def ingest_health_telemetry(
        payload: HealthTelemetryPayload,
        request: Request,
    ) -> dict[str, object]:
        """Accept Adapter reply / health samples into the ops event store.

        Best-effort: when ops runtime is disabled the request is accepted as a
        no-op so Teams Adapter reply paths never fail solely for telemetry.
        """
        ops_runtime = getattr(request.app.state, "ops_runtime", None)
        if ops_runtime is None or not getattr(ops_runtime.settings, "enabled", False):
            return {"accepted": False, "reason": "ops_disabled"}

        occurred_at = utc_now()
        correlation_id = payload.correlationId or f"health-{payload.component}"
        event_payload: dict[str, object] = {
            "component": payload.component,
            "status": payload.status,
            "attributionScope": payload.attributionScope,
        }
        if payload.elapsedMs is not None:
            event_payload["elapsedMs"] = round(payload.elapsedMs, 1)
        if payload.errorType:
            event_payload["errorType"] = payload.errorType
        if payload.channel:
            event_payload["channel"] = payload.channel

        event = OperationalEvent(
            event_id=f"health:{payload.component}:{correlation_id}:{payload.status}",
            event_type="usage.recorded",
            occurred_at=occurred_at,
            environment=ops_runtime.settings.environment,
            correlation_id=correlation_id,
            retention_expires_at=occurred_at
            + timedelta(days=active_retention_days(ops_runtime.settings)),
            payload=event_payload,
        )
        await ops_runtime.ingestion.ingest(event)
        return {"accepted": True, "eventId": event.event_id}
