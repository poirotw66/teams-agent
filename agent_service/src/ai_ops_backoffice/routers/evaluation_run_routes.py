from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, Query
from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext

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
    idempotency_key: str | None = None


class CancelRunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="Cancelled by user", min_length=1, max_length=500)


class ReviewExecutionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_id: str
    metric_id: str
    decision: Literal["PASS", "FAIL", "INCONCLUSIVE", "NOT_APPLICABLE"]
    reason: str = Field(min_length=1, max_length=1000)


class RescoreRunPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judge_version: str = Field(default="ge2-judge-v2", min_length=1)
    metric_version: str = Field(default="ge2-metrics-v2", min_length=1)


def register_evaluation_run_routes(
    app: FastAPI,
    run_service: EvaluationRunService,
    current_actor: Callable[..., ActorContext],
    require_capability: Callable[[ActorContext, str], None],
) -> None:
    router = APIRouter(prefix="/api/evaluations", tags=["Evaluation Runs"])

    @router.post("/runs/preflight")
    async def preflight_run(
        payload: PreflightRunPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
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
            idempotency_key=key,
            correlation_id=correlation_id,
            actor=actor,
            execute_inline=True,
        )

    @router.get("/runs")
    async def list_runs(
        set_version_id: str | None = Query(default=None),
        actor: ActorContext = Depends(current_actor),
    ) -> list[dict[str, Any]]:
        require_capability(actor, "ops.evals.read")
        return run_service.list_runs(set_version_id=set_version_id, actor=actor)

    @router.get("/runs/{run_id}")
    async def get_run(
        run_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return run_service.get_run(run_id, actor=actor)

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(
        run_id: str,
        payload: CancelRunPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.run")
        return run_service.cancel_run(run_id, reason=payload.reason, actor=actor)

    @router.get("/runs/{run_id}/cases")
    async def list_case_executions(
        run_id: str,
        side: Literal["BASELINE", "CANDIDATE"] | None = Query(default=None),
        actor: ActorContext = Depends(current_actor),
    ) -> list[dict[str, Any]]:
        require_capability(actor, "ops.evals.read")
        return run_service.list_case_executions(run_id, side=side, actor=actor)

    @router.get("/runs/{run_id}/cases/{execution_id}")
    async def get_case_execution(
        run_id: str,
        execution_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return run_service.get_case_execution(execution_id, actor=actor)

    @router.post("/runs/{run_id}/reviews")
    async def review_case_execution(
        run_id: str,
        payload: ReviewExecutionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.results.review")
        return run_service.review_execution(
            run_id=run_id,
            execution_id=payload.execution_id,
            metric_id=payload.metric_id,
            decision=payload.decision,
            reason=payload.reason,
            actor=actor,
        )

    @router.post("/runs/{run_id}/rescore")
    async def rescore_run(
        run_id: str,
        payload: RescoreRunPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.results.review")
        return run_service.rescore_run(
            run_id=run_id,
            judge_version=payload.judge_version,
            metric_version=payload.metric_version,
            actor=actor,
        )

    app.include_router(router)
