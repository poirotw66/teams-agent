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
    _acl_filtered_count_from_issue_results,
    _audit_str,
    authorize_tenant,
    build_response,
    log_chat_failure,
    log_chat_success,
    resolve_knowledge_audit_context,
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
        audit = resolve_knowledge_audit_context(
            request.app,
            resolved_settings,
            user_groups=list(payload.user.groups or []),
            execution_context=state.get("execution_context"),
        )
        for key, value in audit.items():
            if value is not None:
                state[key] = value
        acl_filtered = _acl_filtered_count_from_issue_results(
            state.get("issue_results") or []
        )
        if acl_filtered is not None:
            state["knowledge_acl_filtered_count"] = acl_filtered
        cost_summary = await log_chat_success(
            payload,
            correlation_id,
            state,
            usage_metadata,
            started_at,
            resolved_settings=resolved_settings,
            ops_runtime=getattr(request.app.state, "ops_runtime", None),
            knowledge_release_id=_audit_str(audit, "knowledge_release_id"),
            knowledge_selection_mode=_audit_str(audit, "knowledge_selection_mode"),
            knowledge_last_successful_sync_at=_audit_str(
                audit, "knowledge_last_successful_sync_at"
            ),
            is_cloud_production_answer=bool(audit.get("is_cloud_production_answer")),
            service_catalog_version=_audit_str(audit, "service_catalog_version"),
            knowledge_acl_decision=_audit_str(audit, "knowledge_acl_decision"),
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
    first_stage_recorded = False
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
                    if not first_stage_recorded:
                        from agent_service.observability import (
                            METRIC_FIRST_STAGE_LATENCY_MS,
                            record_metric_histogram,
                        )

                        record_metric_histogram(
                            METRIC_FIRST_STAGE_LATENCY_MS,
                            (time.perf_counter() - started_at) * 1000.0,
                            attributes={"component": "agent_workflow"},
                        )
                        first_stage_recorded = True
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
