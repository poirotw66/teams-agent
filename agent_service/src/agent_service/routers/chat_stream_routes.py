"""SSE streaming chat route for the agent service."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.callbacks import get_usage_metadata_callback

from ..contracts import EVALUATION_EVIDENCE_CHANNEL, AgentRequest
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


def _unavailable_error_event(correlation_id: str) -> str:
    return sse(
        "error",
        {
            "detail": "Agent service is temporarily unavailable.",
            "correlationId": correlation_id,
        },
    )


async def _iter_workflow_stream(
    *,
    workflow: AgentWorkflow,
    payload: AgentRequest,
    correlation_id: str,
) -> AsyncIterator[tuple[str, Any]]:
    with get_usage_metadata_callback() as usage_callback:
        async for kind, value in workflow.stream(
            payload, correlation_id=correlation_id
        ):
            yield kind, value
        yield "_usage", usage_callback.usage_metadata


async def _finalize_stream_response(
    *,
    app: FastAPI,
    payload: AgentRequest,
    request: Request,
    resolved_settings: RagSettings,
    correlation_id: str,
    state: Any,
    usage_metadata: Any,
    started_at: float,
) -> AsyncIterator[str]:
    try:
        cost_summary = await log_chat_success(
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
    except Exception as error:  # noqa: BLE001 - HTTP status already committed
        log_chat_failure(
            payload,
            correlation_id,
            error,
            started_at,
            ops_runtime=getattr(request.app.state, "ops_runtime", None),
        )
        yield _unavailable_error_event(correlation_id)
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


async def _stream_chat_events(
    *,
    app: FastAPI,
    payload: AgentRequest,
    request: Request,
    resolved_settings: RagSettings,
    correlation_id: str,
    workflow: AgentWorkflow,
    snapshot: Any,
) -> AsyncIterator[str]:
    from agent_service.operations.policy_runtime import policy_snapshot_scope

    # Sent before the graph starts so the Teams user sees progress
    # within one round-trip instead of waiting for the first node.
    yield sse("stage", {"label": INITIAL_STAGE_LABEL})

    started_at = time.perf_counter()
    state: dict | None = None
    usage_metadata: Any = None
    with policy_snapshot_scope(snapshot):
        try:
            async for kind, value in _iter_workflow_stream(
                workflow=workflow,
                payload=payload,
                correlation_id=correlation_id,
            ):
                if kind == "stage":
                    yield sse("stage", {"label": value})
                elif kind == "state":
                    state = value
                elif kind == "_usage":
                    usage_metadata = value
        except Exception as error:  # noqa: BLE001 - cannot re-raise mid-stream
            log_chat_failure(
                payload,
                correlation_id,
                error,
                started_at,
                ops_runtime=getattr(request.app.state, "ops_runtime", None),
            )
            yield _unavailable_error_event(correlation_id)
            return

        if state is None:
            log_chat_failure(
                payload,
                correlation_id,
                RuntimeError("no state"),
                started_at,
                ops_runtime=getattr(request.app.state, "ops_runtime", None),
            )
            yield _unavailable_error_event(correlation_id)
            return

        async for event in _finalize_stream_response(
            app=app,
            payload=payload,
            request=request,
            resolved_settings=resolved_settings,
            correlation_id=correlation_id,
            state=state,
            usage_metadata=usage_metadata,
            started_at=started_at,
        ):
            yield event


def register_chat_stream_routes(
    app: FastAPI,
    *,
    resolved_settings: RagSettings,
    authorize: Callable[..., None],
) -> None:
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
        if payload.channel == EVALUATION_EVIDENCE_CHANNEL:
            raise HTTPException(status_code=400, detail="Reserved channel.")
        sync_knowledge_to_active_pointer(request.app, resolved_settings)
        authorize_tenant(payload, resolved_settings)
        correlation_id = start_chat(payload)
        workflow: AgentWorkflow = request.app.state.workflow

        from agent_service.operations.policy_runtime import (
            PolicySourceUnavailableError,
            get_policy_runtime,
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

        return StreamingResponse(
            _stream_chat_events(
                app=app,
                payload=payload,
                request=request,
                resolved_settings=resolved_settings,
                correlation_id=correlation_id,
                workflow=workflow,
                snapshot=snapshot,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                # Cloud Run / nginx-style proxies buffer responses by default,
                # which would defeat the point of streaming progress.
                "X-Accel-Buffering": "no",
            },
        )


__all__ = ["register_chat_stream_routes"]
