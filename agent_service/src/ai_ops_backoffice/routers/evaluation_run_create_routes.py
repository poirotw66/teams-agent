"""Evaluation run create / cancel route handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from operations_core.access import ActorContext

from ..evaluation_domain import EvaluationRunService


class PreflightRunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set_version_id: str
    baseline_target: dict[str, Any]
    candidate_target: dict[str, Any]
    limits: dict[str, Any] = Field(default_factory=dict)


class CreateRunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set_version_id: str
    baseline_target: dict[str, Any]
    candidate_target: dict[str, Any]
    mode: Literal["OFFLINE_BENCHMARK", "REAL_RAG"] = "REAL_RAG"
    limits: dict[str, Any] = Field(default_factory=dict)
    repetitions: int = Field(default=1, ge=1, le=5)
    quality_case_id: str | None = None
    idempotency_key: str | None = None
    execute_inline: bool | None = None


class CancelRunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="Cancelled by user", min_length=1, max_length=500)


def register_evaluation_run_create_routes(
    router: APIRouter,
    run_service: EvaluationRunService,
    current_actor: Callable[..., ActorContext],
    require_capability: Callable[[ActorContext, str], None],
) -> None:
    @router.post("/runs/preflight")
    async def preflight_run(
        payload: PreflightRunPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        # Preflight resolves manifests, cost and execution targets for a run;
        # it is part of the run operation, not a read-only result query.
        require_capability(actor, "ops.evals.run")
        res = run_service.preflight_run(
            set_version_id=payload.set_version_id,
            baseline_target=payload.baseline_target,
            candidate_target=payload.candidate_target,
            limits=payload.limits,
            actor=actor,
        )
        return res.model_dump(mode="json")

    @router.post("/runs", status_code=202)
    async def create_run(
        payload: CreateRunPayload,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.run")
        key = idempotency_key or payload.idempotency_key
        return run_service.create_run(
            set_version_id=payload.set_version_id,
            baseline_target=payload.baseline_target,
            candidate_target=payload.candidate_target,
            mode=payload.mode,
            limits=payload.limits,
            repetitions=payload.repetitions,
            quality_case_id=payload.quality_case_id,
            idempotency_key=key,
            correlation_id=correlation_id,
            actor=actor,
            execute_inline=payload.execute_inline,
        )

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(
        run_id: str,
        payload: CancelRunPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.run")
        return run_service.cancel_run(run_id, reason=payload.reason, actor=actor)
