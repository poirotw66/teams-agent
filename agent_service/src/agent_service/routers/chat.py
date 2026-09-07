"""Agent chat and SSE streaming routes."""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.callbacks import get_usage_metadata_callback

from ..contracts import AgentRequest, AgentResponse
from ..deps import sync_knowledge_to_active_pointer
from ..settings import RagSettings
from ..workflow import INITIAL_STAGE_LABEL, AgentWorkflow
from .chat_support import (
    authorize_tenant,
    build_response,
    log_chat_failure,
    log_chat_success,
    sse,
    start_chat,
)


def register_chat_routes(
    app: FastAPI,
    *,
    resolved_settings: RagSettings,
    authorize: Callable[..., None],
) -> None:
    @app.post(
        "/agent/chat",
        response_model=AgentResponse,
        dependencies=[Depends(authorize)],
    )
    async def chat(payload: AgentRequest, request: Request) -> AgentResponse:
        from agent_service.operations.policy_runtime import (
            PolicySourceUnavailableError,
            get_policy_runtime,
            policy_snapshot_scope,
        )

        sync_knowledge_to_active_pointer(request.app, resolved_settings)
        authorize_tenant(payload, resolved_settings)
        correlation_id = start_chat(payload)
        workflow: AgentWorkflow = request.app.state.workflow
        runtime = get_policy_runtime()
        try:
            snapshot = runtime.snapshot() if runtime is not None else None
        except PolicySourceUnavailableError as error:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Policy source unavailable; refusing request without a fixed "
                    f"policy snapshot. Correlation ID: {correlation_id}"
                ),
            ) from error

        started_at = time.perf_counter()
        with policy_snapshot_scope(snapshot):
            try:
                # Keep the token-usage/cost accounting commit 53124a3 added: any
                # LLM call made while running the workflow (Issue Extractor +
                # every Knowledge Service call) is captured here.
                with get_usage_metadata_callback() as usage_callback:
                    state = await workflow.run(payload, correlation_id=correlation_id)
                usage_metadata = usage_callback.usage_metadata
            except Exception as error:
                log_chat_failure(
                    payload, correlation_id, error, started_at,
                    ops_runtime=getattr(request.app.state, "ops_runtime", None),
                )
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent service is temporarily unavailable. Correlation ID: {correlation_id}",
                ) from error

            try:
                cost_summary = await log_chat_success(
                    payload,
                    correlation_id,
                    state,
                    usage_metadata,
                    started_at,
                    resolved_settings=resolved_settings,
                    ops_runtime=getattr(request.app.state, "ops_runtime", None),
                    knowledge_release_id=getattr(request.app.state, "knowledge_release_id", None),
                )
            except Exception as error:
                log_chat_failure(
                    payload, correlation_id, error, started_at,
                    ops_runtime=getattr(request.app.state, "ops_runtime", None),
                )
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent service is temporarily unavailable. Correlation ID: {correlation_id}",
                ) from error
            return build_response(
                state,
                correlation_id,
                channel=payload.channel,
                app=app,
                resolved_settings=resolved_settings,
                cost_summary=cost_summary,
            )

    @app.post(
        "/agent/chat/stream",
        dependencies=[Depends(authorize)],
    )
    async def chat_stream(payload: AgentRequest, request: Request) -> StreamingResponse:
        """Server-Sent Events variant of `/agent/chat` (progress + answer).

        Emits `stage` events while the graph runs, then exactly one terminal
        event: `response` carrying the same `AgentResponse` body `/agent/chat`
        returns, or `error` if the workflow raised.

        The error contract differs from `/agent/chat` by necessity: the HTTP
        status is committed the moment the first byte ships, so a mid-run
        failure cannot become a 503 and is delivered as an `error` event
        instead. Everything a caller can be rejected for *before* the run
        starts -- bad service token, disallowed tenant -- is still a real HTTP
        error, because those checks run before the response begins.
        """
        sync_knowledge_to_active_pointer(request.app, resolved_settings)
        authorize_tenant(payload, resolved_settings)
        correlation_id = start_chat(payload)
        workflow: AgentWorkflow = request.app.state.workflow

        from agent_service.operations.policy_runtime import (
            PolicySourceUnavailableError,
            get_policy_runtime,
            policy_snapshot_scope,
        )

        runtime = get_policy_runtime()
        try:
            snapshot = runtime.snapshot() if runtime is not None else None
        except PolicySourceUnavailableError as error:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Policy source unavailable; refusing request without a fixed "
                    f"policy snapshot. Correlation ID: {correlation_id}"
                ),
            ) from error

        async def events():
            # Sent before the graph starts so the Teams user sees progress
            # within one round-trip instead of waiting for the first node.
            yield sse("stage", {"label": INITIAL_STAGE_LABEL})

            started_at = time.perf_counter()
            state: dict | None = None
            with policy_snapshot_scope(snapshot):
                try:
                    with get_usage_metadata_callback() as usage_callback:
                        async for kind, value in workflow.stream(
                            payload, correlation_id=correlation_id
                        ):
                            if kind == "stage":
                                yield sse("stage", {"label": value})
                            elif kind == "state":
                                state = value
                    usage_metadata = usage_callback.usage_metadata
                except Exception as error:  # noqa: BLE001 - cannot re-raise mid-stream, see docstring
                    log_chat_failure(
                        payload, correlation_id, error, started_at,
                        ops_runtime=getattr(request.app.state, "ops_runtime", None),
                    )
                    yield sse(
                        "error",
                        {
                            "detail": "Agent service is temporarily unavailable.",
                            "correlationId": correlation_id,
                        },
                    )
                    return

                if state is None:
                    # The graph completed without yielding a terminal state. Treat
                    # it as a failure rather than shipping an empty answer.
                    log_chat_failure(
                        payload, correlation_id, RuntimeError("no state"), started_at,
                        ops_runtime=getattr(request.app.state, "ops_runtime", None),
                    )
                    yield sse(
                        "error",
                        {
                            "detail": "Agent service is temporarily unavailable.",
                            "correlationId": correlation_id,
                        },
                    )
                    return

                try:
                    cost_summary = await log_chat_success(
                        payload,
                        correlation_id,
                        state,
                        usage_metadata,
                        started_at,
                        resolved_settings=resolved_settings,
                        ops_runtime=getattr(request.app.state, "ops_runtime", None),
                        knowledge_release_id=getattr(request.app.state, "knowledge_release_id", None),
                    )
                except Exception as error:  # noqa: BLE001 - HTTP status is already committed
                    log_chat_failure(
                        payload, correlation_id, error, started_at,
                        ops_runtime=getattr(request.app.state, "ops_runtime", None),
                    )
                    yield sse(
                        "error",
                        {
                            "detail": "Agent service is temporarily unavailable.",
                            "correlationId": correlation_id,
                        },
                    )
                    return
                yield sse(
                    "response",
                    build_response(
                        state,
                        correlation_id,
                        channel=payload.channel,
                        app=app,
                        resolved_settings=resolved_settings,
                        cost_summary=cost_summary,
                    ).model_dump(mode="json"),
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                # Cloud Run / nginx-style proxies buffer responses by default,
                # which would defeat the point of streaming progress.
                "X-Accel-Buffering": "no",
            },
        )
