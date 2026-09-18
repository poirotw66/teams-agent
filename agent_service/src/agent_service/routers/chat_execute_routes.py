"""Non-streaming chat execute path for agent routes."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from langchain_core.callbacks import get_usage_metadata_callback

from ..contracts import (
    EVALUATION_EVIDENCE_CHANNEL,
    AgentEvaluationResponse,
    AgentRequest,
    AgentResponse,
)
from ..deps import sync_knowledge_to_active_pointer
from ..settings import RagSettings
from ..workflow import AgentWorkflow
from .chat_support import (
    authorize_tenant,
    build_evaluation_response,
    build_response,
    log_chat_failure,
    log_chat_success,
    start_chat,
)


def _policy_snapshot_or_503(correlation_id: str) -> Any:
    from agent_service.operations.policy_runtime import (
        PolicySourceUnavailableError,
        get_policy_runtime,
    )

    runtime = get_policy_runtime()
    try:
        return runtime.snapshot() if runtime is not None else None
    except PolicySourceUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Policy source unavailable; refusing request without a fixed "
                f"policy snapshot. Correlation ID: {correlation_id}"
            ),
        ) from error


async def _run_workflow_with_usage(
    *,
    workflow: AgentWorkflow,
    payload: AgentRequest,
    correlation_id: str,
    request: Request,
    started_at: float,
) -> tuple[Any, Any]:
    try:
        with get_usage_metadata_callback() as usage_callback:
            state = await workflow.run(payload, correlation_id=correlation_id)
        return state, usage_callback.usage_metadata
    except Exception as error:
        log_chat_failure(
            payload,
            correlation_id,
            error,
            started_at,
            ops_runtime=getattr(request.app.state, "ops_runtime", None),
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Agent service is temporarily unavailable. "
                f"Correlation ID: {correlation_id}"
            ),
        ) from error


async def _success_cost_or_503(
    *,
    payload: AgentRequest,
    correlation_id: str,
    state: Any,
    usage_metadata: Any,
    started_at: float,
    request: Request,
    resolved_settings: RagSettings,
) -> Any:
    try:
        return await log_chat_success(
            payload,
            correlation_id,
            state,
            usage_metadata,
            started_at,
            resolved_settings=resolved_settings,
            ops_runtime=getattr(request.app.state, "ops_runtime", None),
            knowledge_release_id=getattr(
                request.app.state, "knowledge_release_id", None
            ),
        )
    except Exception as error:
        log_chat_failure(
            payload,
            correlation_id,
            error,
            started_at,
            ops_runtime=getattr(request.app.state, "ops_runtime", None),
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Agent service is temporarily unavailable. "
                f"Correlation ID: {correlation_id}"
            ),
        ) from error


async def execute_chat(
    payload: AgentRequest,
    request: Request,
    *,
    app: FastAPI,
    resolved_settings: RagSettings,
) -> AgentResponse | AgentEvaluationResponse:
    from agent_service.operations.policy_runtime import policy_snapshot_scope

    sync_knowledge_to_active_pointer(request.app, resolved_settings)
    authorize_tenant(payload, resolved_settings)
    correlation_id = start_chat(payload)
    workflow: AgentWorkflow = request.app.state.workflow
    snapshot = _policy_snapshot_or_503(correlation_id)
    started_at = time.perf_counter()
    with policy_snapshot_scope(snapshot):
        # Keep the token-usage/cost accounting commit 53124a3 added: any
        # LLM call made while running the workflow (Issue Extractor +
        # every Knowledge Service call) is captured here.
        state, usage_metadata = await _run_workflow_with_usage(
            workflow=workflow,
            payload=payload,
            correlation_id=correlation_id,
            request=request,
            started_at=started_at,
        )
        cost_summary = await _success_cost_or_503(
            payload=payload,
            correlation_id=correlation_id,
            state=state,
            usage_metadata=usage_metadata,
            started_at=started_at,
            request=request,
            resolved_settings=resolved_settings,
        )
        response = build_response(
            state,
            correlation_id,
            channel=payload.channel,
            app=app,
            resolved_settings=resolved_settings,
            cost_summary=cost_summary,
        )
        if payload.channel == EVALUATION_EVIDENCE_CHANNEL:
            return build_evaluation_response(response, state)
        return response


def register_chat_execute_routes(
    app: FastAPI,
    *,
    resolved_settings: RagSettings,
    authorize: Callable[..., None],
    authorize_evaluation: Callable[..., None],
) -> None:
    @app.post(
        "/agent/chat",
        response_model=AgentResponse,
        dependencies=[Depends(authorize)],
    )
    async def chat(payload: AgentRequest, request: Request) -> AgentResponse:
        if payload.channel == EVALUATION_EVIDENCE_CHANNEL:
            raise HTTPException(status_code=400, detail="Reserved channel.")
        response = await execute_chat(
            payload,
            request,
            app=app,
            resolved_settings=resolved_settings,
        )
        return AgentResponse.model_validate(response.model_dump())

    @app.post(
        "/agent/evaluation/chat",
        response_model=AgentEvaluationResponse,
        dependencies=[Depends(authorize_evaluation)],
    )
    async def evaluation_chat(
        payload: AgentRequest,
        request: Request,
    ) -> AgentEvaluationResponse:
        evaluation_payload = payload.model_copy(
            update={"channel": EVALUATION_EVIDENCE_CHANNEL}
        )
        response = await execute_chat(
            evaluation_payload,
            request,
            app=app,
            resolved_settings=resolved_settings,
        )
        return AgentEvaluationResponse.model_validate(response.model_dump())


__all__ = ["execute_chat", "register_chat_execute_routes"]
