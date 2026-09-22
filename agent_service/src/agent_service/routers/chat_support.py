"""Chat route helpers: SSE framing, tenant checks, request logging, response build."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import FastAPI, HTTPException

from ..contracts import (
    AgentEvaluationResponse,
    AgentRequest,
    AgentResponse,
    IssueRetrievalTrace,
)
from ..knowledge_release_sync import resolve_selection_mode
from ..operations.contracts import OperationalEvent, utc_now
from ..operations.emitter import _channel_scope
from ..operations.event_identity import LogicalRequestIdentity
from ..operations.runtime import OpsRuntime
from ..service_scope_evidence import get_service_catalog_audit_meta
from ..settings import RagSettings
from ..usage import build_usage_report, convert_usd_to_twd
from ..usage_events import (
    RequestCostSummary,
    build_request_cost_summary,
    derive_request_outcome,
    log_request_cost,
)

logger = logging.getLogger(__name__)


def _audit_str(audit: dict[str, str | bool | int | None], key: str) -> str | None:
    value = audit.get(key)
    return value if isinstance(value, str) else None


def _acl_filtered_count_from_issue_results(issue_results: list[object]) -> int | None:
    """Sum ACL-filtered chunk counts from retrieval stage timings when present."""
    total = 0
    seen = False
    for result in issue_results:
        trace = getattr(result, "retrievalTrace", None)
        if trace is None:
            continue
        timings = getattr(trace, "stageTimingsMs", None) or {}
        if not isinstance(timings, dict):
            continue
        filtered = timings.get("aclFilteredChunks")
        if isinstance(filtered, (int, float)):
            total += int(filtered)
            seen = True
    return total if seen else None


def resolve_knowledge_audit_context(
    app: FastAPI,
    resolved_settings: RagSettings,
    *,
    user_groups: list[str] | tuple[str, ...] | None = None,
    execution_context: object | None = None,
) -> dict[str, str | bool | None]:
    """Collect loaded release / selection / sync metadata for answers and audit."""
    release_id = getattr(app.state, "knowledge_release_id", None)
    pinned_release = getattr(execution_context, "pinned_knowledge_release_id", None)
    if isinstance(pinned_release, str) and pinned_release.strip():
        # In-flight turns keep the release observed when the service was pinned.
        release_id = pinned_release.strip()
    selection_mode: str | None = None
    last_sync_at: str | None = None
    inventory_complete = False
    behind_cloud = True
    aligned_with_cloud = False
    syncer = getattr(app.state, "knowledge_release_syncer", None)
    if syncer is not None:
        try:
            status = syncer.status
            mode = getattr(status, "selection_mode", None)
            if mode is not None:
                selection_mode = mode.value if hasattr(mode, "value") else str(mode)
            last_sync_at = getattr(status, "last_successful_sync_at", None)
            if not release_id:
                release_id = getattr(status, "loaded_release_id", None)
            inventory_complete = bool(
                getattr(status, "runtime_inventory_complete", False)
            )
            behind_cloud = bool(getattr(status, "behind_cloud", True))
            public = status.to_public_dict() if hasattr(status, "to_public_dict") else {}
            aligned_with_cloud = bool(
                public.get("alignedWithCloud") or public.get("matchesCloudProduction")
            )
        except Exception:  # noqa: BLE001 - audit enrichment must not fail the turn
            logger.debug("Knowledge syncer status unavailable for audit fields.", exc_info=True)
    if selection_mode is None:
        try:
            selection_mode = resolve_selection_mode(resolved_settings).value
        except Exception:  # noqa: BLE001
            selection_mode = None
    # Spec §4: only FOLLOW_CLOUD + complete QA mirror may label cloud production.
    # Index-only / behind / PINNED / LOCAL_SANDBOX answers must not claim it.
    is_cloud_production = (
        selection_mode == "FOLLOW_CLOUD"
        and str(getattr(resolved_settings, "knowledge_release_store_mode", "") or "").upper()
        == "GCS"
        and inventory_complete
        and aligned_with_cloud
        and not behind_cloud
    )
    catalog_meta = get_service_catalog_audit_meta()
    catalog_version: str | None = None
    schema = catalog_meta.get("schemaVersion")
    catalog_release = catalog_meta.get("releaseId")
    if isinstance(schema, int) or (isinstance(catalog_release, str) and catalog_release):
        parts = []
        if isinstance(schema, int):
            parts.append(f"schema:{schema}")
        if isinstance(catalog_release, str) and catalog_release.strip():
            parts.append(catalog_release.strip())
        source = catalog_meta.get("source")
        if isinstance(source, str) and source.strip():
            parts.append(source.strip())
        catalog_version = "|".join(parts) if parts else None

    groups = [str(group).strip() for group in (user_groups or []) if str(group).strip()]
    acl_decision = "GROUP_FILTERED" if groups else "PUBLIC_DEFAULT"

    return {
        "knowledge_release_id": release_id if isinstance(release_id, str) else None,
        "knowledge_selection_mode": selection_mode,
        "knowledge_last_successful_sync_at": (
            last_sync_at if isinstance(last_sync_at, str) else None
        ),
        "is_cloud_production_answer": is_cloud_production,
        "service_catalog_version": catalog_version,
        "knowledge_acl_decision": acl_decision,
    }


def sse(event: str, data: dict) -> str:
    """Frame one Server-Sent Event.

    `ensure_ascii=True` is deliberate: the payload is Chinese, and escaping it
    keeps every `data:` line free of raw multi-byte content while JSON itself
    guarantees no embedded newline can break SSE framing.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def authorize_tenant(payload: AgentRequest, resolved_settings: RagSettings) -> None:
    tenant_id = payload.conversation.tenantId
    if resolved_settings.allowed_tenants and tenant_id not in resolved_settings.allowed_tenants:
        raise HTTPException(status_code=403, detail="Tenant is not allowed.")


def start_chat(payload: AgentRequest) -> str:
    # Spec §15.1: derive the Correlation ID exactly ONCE, at this entry
    # point, and never regenerate it downstream (the workflow honors an
    # explicitly-passed value instead of deriving its own).
    correlation_id = (
        payload.correlationId
        or LogicalRequestIdentity(
            payload.conversation.tenantId,
            payload.conversation.conversationId,
            payload.requestId,
        ).value
    )
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
        "Agent request failed: request_id=%s correlation_id=%s error_type=%s elapsed_ms=%s",
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
            and (
                not tenant_id
                or tenant_id in {"00000000-0000-0000-0000-0000000000001", "local-development"}
            )
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
    knowledge_selection_mode: str | None = None,
    knowledge_last_successful_sync_at: str | None = None,
    is_cloud_production_answer: bool | None = None,
    service_catalog_version: str | None = None,
    knowledge_acl_decision: str | None = None,
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
        if knowledge_selection_mode:
            enriched["knowledge_selection_mode"] = knowledge_selection_mode
        if knowledge_last_successful_sync_at:
            enriched["knowledge_last_successful_sync_at"] = (
                knowledge_last_successful_sync_at
            )
        if is_cloud_production_answer is not None:
            enriched["is_cloud_production_answer"] = is_cloud_production_answer
        if service_catalog_version:
            enriched["service_catalog_version"] = service_catalog_version
        if knowledge_acl_decision:
            enriched["knowledge_acl_decision"] = knowledge_acl_decision
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
    selection = state.get("knowledge_selection_mode")
    is_cloud_production = bool(state.get("is_cloud_production_answer"))
    if "is_cloud_production_answer" not in state and isinstance(selection, str):
        is_cloud_production = selection == "FOLLOW_CLOUD" and (
            resolved_settings.knowledge_release_store_mode == "GCS"
        )
    acl_filtered = state.get("knowledge_acl_filtered_count")
    if not isinstance(acl_filtered, int):
        acl_filtered = _acl_filtered_count_from_issue_results(
            state.get("issue_results") or []
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
        knowledgeReleaseId=state.get("knowledge_release_id")
        or getattr(app.state, "knowledge_release_id", None),
        knowledgeSelectionMode=state.get("knowledge_selection_mode"),
        knowledgeLastSuccessfulSyncAt=state.get("knowledge_last_successful_sync_at"),
        isCloudProductionAnswer=is_cloud_production,
        serviceCatalogVersion=state.get("service_catalog_version"),
        knowledgeAclDecision=state.get("knowledge_acl_decision"),
        knowledgeAclFilteredCount=acl_filtered,
    )


def build_evaluation_response(
    response: AgentResponse,
    state: dict,
) -> AgentEvaluationResponse:
    counter = state.get("llm_call_counter")
    traces = [
        IssueRetrievalTrace(
            issueId=result.issueId,
            trace=result.retrievalTrace,
        )
        for result in state.get("issue_results", [])
        if result.retrievalTrace is not None
    ]
    return AgentEvaluationResponse(
        **response.model_dump(mode="python"),
        retrievalTraces=traces,
        llmCallCount=counter.count if counter else 0,
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
    knowledge_backends = sorted({result.backend for result in issue_results if result.backend})
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
