"""Evaluation run read / review route handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from operations_core.access import ActorContext

from ..evaluation_domain import EvaluationRunService


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


def register_evaluation_run_read_routes(
    router: APIRouter,
    run_service: EvaluationRunService,
    current_actor: Callable[..., ActorContext],
    require_capability: Callable[[ActorContext, str], None],
) -> None:
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

    @router.get("/runs/{run_id}/cases/{execution_id}/trajectory")
    async def get_case_trajectory(
        run_id: str,
        execution_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return run_service.get_trajectory(run_id, execution_id, actor=actor)


def register_evaluation_run_review_routes(
    router: APIRouter,
    run_service: EvaluationRunService,
    current_actor: Callable[..., ActorContext],
    require_capability: Callable[[ActorContext, str], None],
) -> None:
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
