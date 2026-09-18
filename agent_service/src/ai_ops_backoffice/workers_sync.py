"""Knowledge sync job runner used by AI Ops background workers."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

import httpx

from operations_core.access import ActorContext

from .faq_domain import FaqDomainError

logger = logging.getLogger(__name__)

__all__ = ["build_run_sync_job"]

SyncJobRunner = Callable[[str], Awaitable[None]]


def build_run_sync_job(
    *,
    resolved_settings,
    query_service,
    sync_service,
    budget_service,
    notification_dispatcher,
    knowledge_transport,
    sync_transport,
    sync_worker: ActorContext,
) -> SyncJobRunner:
    """Return the async sync-job callback bound to runtime collaborators."""

    async def run_sync_job(job_id: str) -> None:
        started_at = time.perf_counter()
        job: dict[str, Any] = {"correlation_id": job_id}

        async def emit_index_health(
            *,
            status: str,
            error_summary: str | None = None,
            extra: dict[str, Any] | None = None,
        ) -> None:
            await _emit_index_health(
                query_service=query_service,
                job_id=job_id,
                job=job,
                started_at=started_at,
                status=status,
                error_summary=error_summary,
                extra=extra,
            )

        async def record_sync_failure(error_summary: str) -> None:
            await _record_sync_failure(
                sync_service=sync_service,
                budget_service=budget_service,
                notification_dispatcher=notification_dispatcher,
                sync_worker=sync_worker,
                emit_index_health=emit_index_health,
                job_id=job_id,
                error_summary=error_summary,
            )

        try:
            await _execute_sync_job(
                resolved_settings=resolved_settings,
                sync_service=sync_service,
                knowledge_transport=knowledge_transport,
                sync_transport=sync_transport,
                sync_worker=sync_worker,
                job_id=job_id,
                job=job,
                emit_index_health=emit_index_health,
                record_sync_failure=record_sync_failure,
            )
        except httpx.TimeoutException:
            logger.exception("Sync job %s timed out", job_id)
            with suppress(FaqDomainError):
                await record_sync_failure("SYNC_ADAPTER_TIMEOUT")
        except Exception as error:
            logger.exception("Sync job %s failed", job_id)
            with suppress(FaqDomainError):
                await record_sync_failure(type(error).__name__)

    return run_sync_job


async def _emit_index_health(
    *,
    query_service,
    job_id: str,
    job: dict[str, Any],
    started_at: float,
    status: str,
    error_summary: str | None,
    extra: dict[str, Any] | None,
) -> None:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    payload: dict[str, Any] = {
        "attributionScope": "HEALTH_TELEMETRY",
        "syncJobId": job_id,
    }
    if extra:
        payload.update(extra)
    if error_summary:
        payload["errorType"] = error_summary
    try:
        await query_service.record_component_usage(
            component="knowledge_index",
            status=status,
            elapsed_ms=elapsed_ms,
            correlation_id=job.get("correlation_id") or job_id,
            payload=payload,
        )
    except Exception:
        logger.exception(
            "Failed to emit knowledge_index health telemetry for sync job %s",
            job_id,
        )


async def _record_sync_failure(
    *,
    sync_service,
    budget_service,
    notification_dispatcher,
    sync_worker: ActorContext,
    emit_index_health: Callable[..., Awaitable[None]],
    job_id: str,
    error_summary: str,
) -> None:
    failed = sync_service.set_stage(
        job_id,
        status="FAILED",
        actor=sync_worker,
        error_summary=error_summary,
    )
    failed_job = failed["job"]
    status = "TIMEOUT" if "timeout" in error_summary.lower() else "FAILED"
    await emit_index_health(
        status=status,
        error_summary=error_summary,
        extra={
            "scopeType": failed_job.get("scope_type"),
            "ownerUnitId": failed_job.get("owner_unit_id"),
        },
    )
    try:
        alert_result = budget_service.trigger_operational_alert(
            alert_type="SYNC_FAILURE",
            severity="CRITICAL",
            scope_type="SYNC_JOB",
            scope_id=job_id,
            period_key=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            owner_unit_id=failed_job.get("owner_unit_id", "IT"),
            summary=(
                f"Knowledge sync failed for {failed_job.get('scope_type', 'ALL')} "
                f"(job {job_id}): {error_summary}"
            ),
            actor=sync_worker,
        )
        if alert_result.get("triggered") and alert_result.get("alert"):
            await notification_dispatcher.dispatch_for_alert(
                alert_result["alert"]["alert_id"],
                actor=sync_worker,
            )
    except Exception:
        logger.exception("Failed to trigger sync failure alert for %s", job_id)


async def _execute_sync_job(
    *,
    resolved_settings,
    sync_service,
    knowledge_transport,
    sync_transport,
    sync_worker: ActorContext,
    job_id: str,
    job: dict[str, Any],
    emit_index_health: Callable[..., Awaitable[None]],
    record_sync_failure: Callable[[str], Awaitable[None]],
) -> None:
    validating = sync_service.set_stage(job_id, status="VALIDATING", actor=sync_worker)
    job.clear()
    job.update(validating["job"])
    adapter_url = resolved_settings.sync_adapter_url
    if not adapter_url and sync_transport is not None:
        adapter_url = resolved_settings.knowledge_portal_url
    if not adapter_url:
        await record_sync_failure("SYNC_ADAPTER_UNAVAILABLE")
        return
    sync_service.set_stage(job_id, status="BUILDING", actor=sync_worker)
    headers = {
        "X-Portal-User-Id": "ai-ops-sync-worker",
        "X-Portal-User-Name": "AI Ops Sync Worker",
        "X-Portal-Role": "PLATFORM",
    }
    if resolved_settings.service_token:
        headers["Authorization"] = f"Bearer {resolved_settings.service_token}"
    effective_sync_transport = sync_transport
    if effective_sync_transport is None and adapter_url == resolved_settings.knowledge_portal_url:
        effective_sync_transport = knowledge_transport
    async with httpx.AsyncClient(timeout=120.0, transport=effective_sync_transport) as client:
        response = await client.post(
            f"{adapter_url.rstrip('/')}/api/sync",
            headers=headers,
            json={
                "scopeType": job["scope_type"],
                "scopeIds": job["scope_ids"],
                "correlationId": job["correlation_id"],
                "resumeCheckpoint": job["retry_checkpoint_stage"],
            },
        )
    if response.status_code >= 400:
        await record_sync_failure(f"Adapter returned HTTP {response.status_code}")
        return
    result = response.json()
    if not result.get("targetRelease") or not result.get("indexSettingVersion"):
        await record_sync_failure("SYNC_RELEASE_EVIDENCE_MISSING")
        return
    sync_service.set_stage(
        job_id,
        status="VERIFYING",
        actor=sync_worker,
        document_count=int(result.get("documentCount") or 0),
        warnings=tuple(result.get("warnings") or ()),
    )
    sync_service.set_stage(
        job_id,
        status="COMPLETED",
        actor=sync_worker,
        document_count=int(result.get("documentCount") or 0),
        warnings=tuple(result.get("warnings") or ()),
        target_release=result.get("targetRelease"),
        index_setting_version=result.get("indexSettingVersion"),
        artifact_uri=result.get("artifactUri"),
    )
    await emit_index_health(
        status="SUCCESS",
        extra={
            "targetRelease": result.get("targetRelease"),
            "indexSettingVersion": result.get("indexSettingVersion"),
            "documentCount": int(result.get("documentCount") or 0),
        },
    )
