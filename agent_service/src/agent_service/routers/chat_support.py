"""Chat route helpers: SSE framing, tenant checks, request logging, response build."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import FastAPI, HTTPException

from ..contracts import AgentRequest, AgentResponse
from ..operations.contracts import OperationalEvent, utc_now
from ..operations.emitter import _channel_scope
from ..operations.event_identity import LogicalRequestIdentity
from ..operations.runtime import OpsRuntime
from ..settings import RagSettings
from ..usage import build_usage_report, convert_usd_to_twd
from ..usage_events import (
    RequestCostSummary,
    build_request_cost_summary,
    derive_request_outcome,
    log_request_cost,
)

logger = logging.getLogger(__name__)


def sse(event: str, data: dict) -> str:
    """Frame one Server-Sent Event.

    `ensure_ascii=True` is deliberate: the payload is Chinese, and escaping it
    keeps every `data:` line free of raw multi-byte content while JSON itself
    guarantees no embedded newline can break SSE framing.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def authorize_tenant(payload: AgentRequest, resolved_settings: RagSettings) -> None:
    tenant_id = payload.conversation.tenantId
    if (
        resolved_settings.allowed_tenants
        and tenant_id not in resolved_settings.allowed_tenants
    ):
        raise HTTPException(status_code=403, detail="Tenant is not allowed.")


def start_chat(payload: AgentRequest) -> str:
    # Spec §15.1: derive the Correlation ID exactly ONCE, at this entry
    # point, and never regenerate it downstream (the workflow honors an
    # explicitly-passed value instead of deriving its own).
    correlation_id = payload.correlationId or LogicalRequestIdentity(
        payload.conversation.tenantId,
        payload.conversation.conversationId,
        payload.requestId,
    ).value
    logger.info(
        "Agent request started: request_id=%s channel=%s correlation_id=%s",
        payload.requestId,
        payload.channel,
        correlation_id,
    )
    return correlation_id


def log_chat_failure(
    payload: AgentRequest,
    correlation_id: str,
    error: BaseException,
    started_at: float,
    *,
    ops_runtime: OpsRuntime | None = None,
) -> None:
    # Spec §17/§15.2: never a stack trace to the caller, and log the
    # error TYPE only (never the exception's raw text, which could
    # embed request content).
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    error_type = type(error).__name__
    logger.error(
        "Agent request failed: request_id=%s correlation_id=%s "
        "error_type=%s elapsed_ms=%s",
        payload.requestId,
        correlation_id,
        error_type,
        elapsed_ms,
    )
    if ops_runtime is not None and ops_runtime.settings.enabled:
        now = utc_now()
        conversation_id = payload.conversation.conversationId
        channel_scope = _channel_scope(payload.channel)
        tenant_id = payload.conversation.tenantId
        if (
            channel_scope == "playground"
            and ops_runtime.settings.environment in {"dev", "test"}
            and (not tenant_id or tenant_id in {"00000000-0000-0000-0000-0000000000001", "local-development"})
        ):
            tenant_id = "local-development"
        failed_event = OperationalEvent(
            event_id=f"{payload.requestId}:request.failed",
            event_type="request.failed",
            occurred_at=now,
            environment=ops_runtime.settings.environment,
            tenant_id=tenant_id,
            team_id=payload.conversation.teamId,
            channel_scope=channel_scope,
            conversation_id=conversation_id,
            turn_id=f"{payload.conversation.tenantId}:{conversation_id}:{payload.requestId}",
            request_id=payload.requestId,
            correlation_id=correlation_id,
            payload={
                "component": "agent-service",
                "errorType": error_type,
                "elapsedMs": elapsed_ms,
            },
        )
        asyncio.create_task(ops_runtime.ingestion.ingest(failed_event))


async def log_chat_success(
    payload: AgentRequest,
    correlation_id: str,
    state: dict,
    usage_metadata: dict,
    started_at: float,
    *,
    resolved_settings: RagSettings,
    ops_runtime: OpsRuntime | None = None,
    knowledge_release_id: str | None = None,
) -> RequestCostSummary | None:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    log_chat_request(payload, state, elapsed_ms=elapsed_ms, error_type=None)
    usage_fields = build_usage_report(usage_metadata).log_fields()
    logger.info(
        "Agent request usage: request_id=%s correlation_id=%s input_tokens=%s "
        "output_tokens=%s total_tokens=%s embedding_tokens=%s estimated_cost_usd=%s "
        "usage=%s",
        payload.requestId,
        correlation_id,
        usage_fields["input_tokens"],
        usage_fields["output_tokens"],
        usage_fields["total_tokens"],
        usage_fields["embedding_tokens"],
        usage_fields["estimated_cost_usd"],
        usage_fields,
    )
    execution_context = state.get("execution_context")
    counter = state.get("llm_call_counter")
    if execution_context is None:
        return None
    summary = build_request_cost_summary(
        execution_context.usage_collector,
        langchain_usage=usage_metadata,
        outcome=derive_request_outcome(state),
        elapsed_ms=elapsed_ms,
        llm_call_count=counter.count if counter else 0,
        embedding_model=resolved_settings.embedding_model,
    )
    log_request_cost(summary)
    if ops_runtime is not None:
        enriched = dict(state)
        if knowledge_release_id:
            enriched["knowledge_release_id"] = knowledge_release_id
        await ops_runtime.emitter.emit_turn(payload, enriched, cost_summary=summary)
    return summary


def build_response(
    state: dict,
    correlation_id: str,
    *,
    channel: str,
    app: FastAPI,
    resolved_settings: RagSettings,
    cost_summary: RequestCostSummary | None = None,
) -> AgentResponse:
    estimated_cost_usd: float | None = None
    estimated_cost_twd: float | None = None
    cost_complete: bool | None = None
    runtime = getattr(app.state, "governance_runtime", None)
    cost_flag_enabled = True
    if runtime is not None:
        cost_flag_enabled = runtime.cost_display_enabled()
    if cost_flag_enabled and resolved_settings.should_show_turn_cost(channel):
        cost_complete = cost_summary.cost_complete if cost_summary else False
        if cost_summary and cost_summary.estimated_cost_usd is not None:
            estimated_cost_usd = round(cost_summary.estimated_cost_usd, 8)
            estimated_cost_twd = convert_usd_to_twd(
                estimated_cost_usd,
                resolved_settings.usd_twd_exchange_rate,
            )
    return AgentResponse(
        answer=state.get("final_response", ""),
        traceId=correlation_id,
        correlationId=correlation_id,
        citations=state.get("citations", []),
        images=state.get("images", []),
        issueResults=state.get("issue_results", []),
        feedbackEnabled=state.get("feedback_enabled", False),
        estimatedCostUsd=estimated_cost_usd,
        estimatedCostTwd=estimated_cost_twd,
        costComplete=cost_complete,
    )


def log_chat_request(
    payload: AgentRequest,
    state: dict,
    *,
    elapsed_ms: float,
    error_type: str | None,
) -> None:
    """Emit the single structured log line required by spec §15.2.

    Fields logged (and ONLY these — never API keys/tokens/passwords/
    verification codes/full message text/a stack trace, per spec §15.2/§17):
    correlation_id, conversation_id, user_id, issue_count, issue_routes,
    faq_hit, knowledge_backend, knowledge_hit, follow_up_asked,
    ticket_created, elapsed_ms, error_type, llm_call_count.
    """
    issues = state.get("issues", [])
    issue_results = state.get("issue_results", [])
    conversation = state.get("conversation")
    counter = state.get("llm_call_counter")

    issue_routes = [f"{issue.id}:{issue.route}" for issue in issues]
    faq_hit = any(result.resultType == "FAQ_ANSWERED" for result in issue_results)
    knowledge_hit = any(result.resultType == "KNOWLEDGE_ANSWERED" for result in issue_results)
    knowledge_backends = sorted(
        {result.backend for result in issue_results if result.backend}
    )
    follow_up_asked = any(result.resultType == "NEED_MORE_INFO" for result in issue_results)
    ticket_created = any(result.resultType == "TICKET_CREATED" for result in issue_results)

    logger.info(
        "Agent request completed: request_id=%s correlation_id=%s conversation_id=%s "
        "user_id=%s issue_count=%s issue_routes=%s faq_hit=%s knowledge_backend=%s "
        "knowledge_hit=%s follow_up_asked=%s ticket_created=%s elapsed_ms=%s "
        "error_type=%s llm_call_count=%s",
        payload.requestId,
        state.get("correlation_id"),
        conversation.conversationId if conversation else None,
        payload.user.entraObjectId or payload.user.teamsUserId,
        len(issues),
        issue_routes,
        faq_hit,
        knowledge_backends,
        knowledge_hit,
        follow_up_asked,
        ticket_created,
        elapsed_ms,
        error_type,
        counter.count if counter else 0,
    )
