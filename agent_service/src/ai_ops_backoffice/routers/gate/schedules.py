"""Gate schedule and source-impact routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from operations_core.access import ActorContext

from .context import GateRouteContext
from .models import CreateSchedulePayload, UpdateSchedulePayload


def register_schedule_routes(router: APIRouter, ctx: GateRouteContext) -> None:
    gate_service = ctx.gate_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @router.get("/source-impacts")
    async def get_source_impacts(
        source_type: str = Query(...),
        source_id: str = Query(...),
        source_version: str | None = Query(default=None),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        impact = gate_service.analyze_source_impact(
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
        )
        return {"impact": impact.model_dump(mode="json")}

    @router.get("/schedules")
    async def list_schedules(actor: ActorContext = Depends(current_actor)) -> list[dict[str, Any]]:
        require_capability(actor, "ops.evals.read")
        schedules = gate_service.repository.list_schedules()
        return [s.model_dump(mode="json") for s in schedules]

    @router.post("/schedules")
    async def create_schedule(
        payload: CreateSchedulePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        tenant_id = actor.tenant_id or "default"
        schedule = gate_service.create_schedule(
            schedule_id=payload.schedule_id,
            tenant_id=tenant_id,
            name=payload.name,
            set_version_id=payload.set_version_id,
            frequency=payload.frequency,
            budget_limit_usd=payload.budget_limit_usd,
            target_refs=payload.target_refs,
            created_by=actor.user_id,
        )
        return {"schedule": schedule.model_dump(mode="json")}

    @router.patch("/schedules/{schedule_id}")
    async def update_schedule(
        schedule_id: str,
        payload: UpdateSchedulePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        schedule = gate_service.update_schedule(
            schedule_id=schedule_id,
            is_enabled=payload.is_enabled,
            frequency=payload.frequency,
            budget_limit_usd=payload.budget_limit_usd,
            target_refs=payload.target_refs,
            updated_by=actor.user_id,
        )
        return {"schedule": schedule.model_dump(mode="json")}
