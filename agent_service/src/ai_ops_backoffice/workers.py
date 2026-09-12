"""Background workers for AI Ops backoffice app lifespan."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import DEFAULT_TIMEZONE

from .faq_domain import FaqDomainError

logger = logging.getLogger(__name__)


async def run_scheduled_retention_sweep(
    *,
    actor: ActorContext,
    query_service,
    sync_service=None,
    budget_service=None,
    example_service=None,
    quality_service=None,
    governance_service=None,
) -> dict[str, Any]:
    """Execute one cross-domain retention sweep using ACTIVE policy TTLs.

    Extracted from the lifespan worker so scheduled behavior is unit-testable
    without waiting for the background interval.
    """
    from .retention_runtime import resolve_active_retention_ttls

    ttls = resolve_active_retention_ttls(governance_service)
    retention_days = int(ttls["retention_days"])
    audit_retention_days = int(ttls["audit_retention_days"])

    events_res = await query_service.purge_expired_events()
    export_removed = 0
    if hasattr(query_service, "export_jobs") and query_service.export_jobs:
        export_removed = await query_service.export_jobs.purge_expired_jobs()

    examples_res = (
        example_service.purge_expired(actor=actor, retention_days=retention_days)
        if example_service
        else {"removed": 0}
    )
    quality_res = (
        quality_service.purge_expired(actor=actor, retention_days=retention_days)
        if quality_service
        else {"total": 0}
    )
    sync_res = (
        sync_service.purge_expired(actor=actor, retention_days=retention_days)
        if sync_service
        else {"total": 0}
    )
    budget_res = (
        budget_service.purge_expired(actor=actor, retention_days=retention_days)
        if budget_service
        else {"total": 0}
    )
    gov_res = (
        governance_service.purge_expired(
            actor=actor,
            retention_days=retention_days,
            audit_retention_days=audit_retention_days,
        )
        if governance_service is not None and hasattr(governance_service, "purge_expired")
        else {"totalRemoved": 0}
    )

    result = {
        "retentionDays": retention_days,
        "auditRetentionDays": audit_retention_days,
        "policy": ttls.get("policy"),
        "operationalEvents": events_res.get("removed", 0) if isinstance(events_res, dict) else 0,
        "exportJobs": export_removed,
        "examples": examples_res.get("removed", 0) if isinstance(examples_res, dict) else 0,
        "quality": quality_res.get("total", 0) if isinstance(quality_res, dict) else 0,
        "sync": sync_res.get("total", 0) if isinstance(sync_res, dict) else 0,
        "budget": budget_res.get("total", 0) if isinstance(budget_res, dict) else 0,
        "governance": gov_res,
    }
    logger.info(
        "Scheduled cross-domain retention sweep completed successfully "
        "(retentionDays=%s auditRetentionDays=%s).",
        retention_days,
        audit_retention_days,
    )
    return result


def install_background_runtime(
    *,
    resolved_settings,
    query_service,
    sync_service,
    budget_service,
    notification_dispatcher,
    knowledge_transport,
    sync_transport,
    example_service=None,
    quality_service=None,
    governance_service=None,
    job_worker=None,
    eval_scheduler=None,
    freshness_tracker=None,
):
    """Build sync worker callbacks and FastAPI lifespan."""

    sync_worker = ActorContext(
        user_id="ai-ops-sync-worker",
        display_name="AI Ops Sync Worker",
        role="SYSTEM_ADMIN",
        owner_unit_ids=(),
    )

    async def run_sync_job(job_id: str) -> None:
        started_at = time.perf_counter()

        async def emit_index_health(
            *,
            status: str,
            error_summary: str | None = None,
            extra: dict[str, Any] | None = None,
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

        async def record_sync_failure(error_summary: str) -> None:
            failed = sync_service.set_stage(
                job_id,
                status="FAILED",
                actor=sync_worker,
                error_summary=error_summary,
            )
            failed_job = failed["job"]
            status = (
                "TIMEOUT"
                if "timeout" in error_summary.lower()
                else "FAILED"
            )
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
                    summary=f"Knowledge sync failed for {failed_job.get('scope_type', 'ALL')} (job {job_id}): {error_summary}",
                    actor=sync_worker,
                )
                if alert_result.get("triggered") and alert_result.get("alert"):
                    await notification_dispatcher.dispatch_for_alert(
                        alert_result["alert"]["alert_id"],
                        actor=sync_worker,
                    )
            except Exception:
                logger.exception("Failed to trigger sync failure alert for %s", job_id)

        job: dict[str, Any] = {"correlation_id": job_id}
        try:
            validating = sync_service.set_stage(job_id, status="VALIDATING", actor=sync_worker)
            job = validating["job"]
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
        except httpx.TimeoutException:
            logger.exception("Sync job %s timed out", job_id)
            with suppress(FaqDomainError):
                await record_sync_failure("SYNC_ADAPTER_TIMEOUT")
        except Exception as error:
            logger.exception("Sync job %s failed", job_id)
            with suppress(FaqDomainError):
                await record_sync_failure(type(error).__name__)

    async def check_api_health_alerts(actor: ActorContext) -> list[dict[str, Any]]:
        health = await query_service.health_summary()
        triggered_alerts: list[dict[str, Any]] = []
        today_key = datetime.now(timezone.utc).astimezone(ZoneInfo(DEFAULT_TIMEZONE)).strftime(
            "%Y-%m-%d"
        )
        for comp in health.get("components", []):
            comp_id = str(comp.get("id") or "")
            if not comp_id:
                continue
            status = str(comp.get("status", "READY")).upper()
            note = str(comp.get("note", ""))
            error_rate = float(comp.get("errorRate") or 0.0)

            is_down = status in {"DOWN", "FAILED", "UNAVAILABLE"}
            is_degraded = status in {"DEGRADED"} or error_rate >= 0.05

            if is_down or is_degraded:
                severity = "CRITICAL" if is_down else "WARNING"
                summary = f"API anomaly in {comp_id}: status={status}, errorRate={error_rate:.2%}; {note}".strip()
                try:
                    alert_res = budget_service.trigger_operational_alert(
                        alert_type="API_ANOMALY",
                        severity=severity,
                        scope_type="SERVICE",
                        scope_id=comp_id,
                        period_key=today_key,
                        owner_unit_id="IT",
                        summary=summary,
                        actual_value=error_rate,
                        actor=actor,
                    )
                    if alert_res.get("triggered") and alert_res.get("alert"):
                        triggered_alerts.append(alert_res["alert"])
                        await notification_dispatcher.dispatch_for_alert(
                            alert_res["alert"]["alert_id"],
                            actor=actor,
                        )
                except Exception:
                    logger.exception("Failed to record API anomaly alert for %s", comp_id)
        return triggered_alerts

    async def evaluate_all_budgets(actor: ActorContext) -> dict[str, Any]:
        evaluated_policies = 0
        evaluated_users = 0
        triggered_alerts: list[dict[str, Any]] = []

        policies = budget_service.list_policies(actor=actor)
        for policy in policies:
            if not policy.get("enabled", True):
                continue
            try:
                usage = await query_service.budget_usage(
                    actor,
                    scope_type=str(policy["scope_type"]),
                    scope_id=str(policy["scope_id"]),
                    period_type=str(policy["period"]),
                    measure=str(policy["measure"]),
                )
                res = budget_service.evaluate(
                    str(policy["policy_id"]),
                    period_key=str(usage["periodKey"]),
                    actual_value=float(usage["actualValue"]),
                    coverage=float(usage["coverage"]),
                    pricing_version=str(usage["pricingVersion"]),
                    exchange_rate_version=str(usage["exchangeRateVersion"]),
                    actor=actor,
                )
                evaluated_policies += 1
                if res.get("triggered") and res.get("alert"):
                    triggered_alerts.append(res["alert"])
                    await notification_dispatcher.dispatch_for_alert(
                        res["alert"]["alert_id"],
                        actor=actor,
                    )
            except Exception:
                logger.exception("Failed to evaluate policy %s", policy.get("policy_id"))

        if resolved_settings.default_personal_daily_budget_enabled:
            today_period = query_service._resolve_period(preset="today")
            active_actors = await query_service.list_active_actors_for_budget(actor, today_period)
            definitions = query_service.metrics_definitions()
            pricing_ver = str(definitions.get("pricingVersion", "v1"))
            rate_ver = str(
                definitions.get("exchangeRateVersion") or definitions.get("pricingVersion", "v1")
            )

            covered_users = {
                p["scope_id"]
                for p in policies
                if p.get("scope_type") == "PERSONAL"
                and p.get("period") == "DAILY"
                and p.get("measure") == "TWD"
                and p.get("enabled", True)
            }

            for user_id in active_actors:
                if user_id in covered_users:
                    continue
                try:
                    personal_policy = budget_service.ensure_personal_policy(
                        user_id=user_id,
                        warning_threshold=resolved_settings.default_personal_daily_warning_threshold,
                        critical_threshold=resolved_settings.default_personal_daily_budget_threshold,
                        pricing_version=pricing_ver,
                        exchange_rate_version=rate_ver,
                        actor=actor,
                    )
                    usage = await query_service.budget_usage(
                        actor,
                        scope_type="PERSONAL",
                        scope_id=user_id,
                        period_type="DAILY",
                        measure="TWD",
                    )
                    res = budget_service.evaluate(
                        str(personal_policy["policy_id"]),
                        period_key=str(usage["periodKey"]),
                        actual_value=float(usage["actualValue"]),
                        coverage=float(usage["coverage"]),
                        pricing_version=str(usage["pricingVersion"]),
                        exchange_rate_version=str(usage["exchangeRateVersion"]),
                        actor=actor,
                    )
                    evaluated_users += 1
                    if res.get("triggered") and res.get("alert"):
                        triggered_alerts.append(res["alert"])
                        await notification_dispatcher.dispatch_for_alert(
                            res["alert"]["alert_id"],
                            actor=actor,
                        )
                except Exception:
                    logger.exception("Failed to evaluate personal daily budget for user %s", user_id)

        if resolved_settings.api_anomaly_check_enabled:
            anomaly_alerts = await check_api_health_alerts(actor)
            triggered_alerts.extend(anomaly_alerts)

        dispatched = await notification_dispatcher.dispatch_pending(actor=actor)

        return {
            "evaluatedPolicies": evaluated_policies,
            "evaluatedUsers": evaluated_users,
            "triggeredAlerts": len(triggered_alerts),
            "alerts": triggered_alerts,
            "dispatchedDeliveries": len(dispatched),
        }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.ops_store_path.mkdir(parents=True, exist_ok=True)
        if not getattr(resolved_settings, "workers_enabled", True):
            logger.info(
                "AI Ops background workers are disabled (workers_enabled=False). "
                "API server running without background worker tasks."
            )
            yield
            return

        stop_sweeper = asyncio.Event()
        query_service.export_jobs.configure_execution_backend(query_service)
        try:
            recovered = await query_service.export_jobs.recover_interrupted_jobs()
            if recovered:
                logger.info("Recovered %s interrupted export jobs", recovered)
        except Exception:
            logger.exception("Failed to recover interrupted export jobs.")

        async def sweep_expired_exports() -> None:
            while not stop_sweeper.is_set():
                try:
                    await query_service.export_jobs.purge_expired_jobs()
                except Exception:
                    logger.exception("Failed to purge expired export jobs.")
                try:
                    await asyncio.wait_for(stop_sweeper.wait(), timeout=60)
                except TimeoutError:
                    continue

        async def materialize_daily_aggregates_worker() -> None:
            # Warm aggregates shortly after boot, then refresh periodically so
            # operations_summary can prefer aggregate rows when coverage is complete.
            first_delay_seconds = 5
            refresh_interval_seconds = 300
            try:
                await asyncio.wait_for(stop_sweeper.wait(), timeout=first_delay_seconds)
                return
            except TimeoutError:
                pass
            while not stop_sweeper.is_set():
                try:
                    result = await query_service.rebuild_daily_aggregates(days=30)
                    logger.info(
                        "Materialized daily aggregates written=%s days=%s",
                        result.get("written"),
                        len(result.get("days") or []),
                    )
                    if freshness_tracker is not None:
                        freshness_tracker.record_sync_success("reporting")
                        freshness_tracker.record_sync_success("daily_aggregates")
                        freshness_tracker.record_sync_success("operations_overview")
                        freshness_tracker.record_sync_success("operations-overview")
                        freshness_tracker.record_stage_event(
                            "operations_overview",
                            "AGGREGATION_COMPLETED",
                        )
                        freshness_tracker.record_stage_event(
                            "operations-overview",
                            "AGGREGATION_COMPLETED",
                        )
                except Exception:
                    logger.exception("Failed to materialize daily aggregates.")
                try:
                    await asyncio.wait_for(
                        stop_sweeper.wait(), timeout=refresh_interval_seconds
                    )
                except TimeoutError:
                    continue

        async def budget_evaluation_worker() -> None:
            first_delay_seconds = 5
            interval_seconds = resolved_settings.budget_eval_interval_seconds
            try:
                await asyncio.wait_for(stop_sweeper.wait(), timeout=first_delay_seconds)
                return
            except TimeoutError:
                pass
            while not stop_sweeper.is_set():
                try:
                    res = await evaluate_all_budgets(sync_worker)
                    logger.info("Auto budget & anomaly evaluation completed: %s", res)
                except Exception:
                    logger.exception("Failed to run auto budget evaluation.")
                try:
                    await asyncio.wait_for(stop_sweeper.wait(), timeout=interval_seconds)
                except TimeoutError:
                    continue

        async def retention_sweep_worker() -> None:
            first_delay_seconds = 10
            interval_seconds = getattr(resolved_settings, "retention_eval_interval_seconds", 3600)
            try:
                await asyncio.wait_for(stop_sweeper.wait(), timeout=first_delay_seconds)
                return
            except TimeoutError:
                pass
            while not stop_sweeper.is_set():
                try:
                    await run_scheduled_retention_sweep(
                        actor=sync_worker,
                        query_service=query_service,
                        sync_service=sync_service,
                        budget_service=budget_service,
                        example_service=example_service,
                        quality_service=quality_service,
                        governance_service=governance_service,
                    )
                except Exception:
                    logger.exception("Failed to run scheduled retention sweep.")
                try:
                    await asyncio.wait_for(stop_sweeper.wait(), timeout=interval_seconds)
                except TimeoutError:
                    continue

        if job_worker is not None:
            job_worker.start()

        async def eval_scheduler_worker() -> None:
            first_delay_seconds = 5
            interval_seconds = getattr(resolved_settings, "eval_schedule_interval_seconds", 60)
            try:
                await asyncio.wait_for(stop_sweeper.wait(), timeout=first_delay_seconds)
                return
            except TimeoutError:
                pass
            while not stop_sweeper.is_set():
                try:
                    dispatched = eval_scheduler.scan_and_dispatch_due_schedules()
                    if dispatched:
                        logger.info("Evaluation scheduler dispatched %s due schedules", len(dispatched))
                except Exception:
                    logger.exception("Failed to scan and dispatch due evaluation schedules.")
                try:
                    await asyncio.wait_for(stop_sweeper.wait(), timeout=interval_seconds)
                except TimeoutError:
                    continue

        async def freshness_worker() -> None:
            first_delay_seconds = 10
            interval_seconds = getattr(resolved_settings, "freshness_eval_interval_seconds", 300)
            # Keep tracker stale threshold aligned with the heartbeat cadence.
            if freshness_tracker is not None:
                freshness_tracker._heartbeat_interval = float(interval_seconds)
                freshness_tracker._worker_stale_threshold = float(interval_seconds) * 2
            try:
                await asyncio.wait_for(stop_sweeper.wait(), timeout=first_delay_seconds)
                return
            except TimeoutError:
                pass
            while not stop_sweeper.is_set():
                try:
                    freshness_tracker.record_worker_heartbeat()
                except Exception:
                    logger.exception("Failed to record worker heartbeat for freshness.")
                try:
                    await asyncio.wait_for(stop_sweeper.wait(), timeout=interval_seconds)
                except TimeoutError:
                    continue

        tasks_to_cancel: list[asyncio.Task] = []
        sweeper = asyncio.create_task(sweep_expired_exports())
        tasks_to_cancel.append(sweeper)
        recovery = asyncio.create_task(
            query_service.export_jobs.run_recovery_scanner(stop_sweeper)
        )
        tasks_to_cancel.append(recovery)
        aggregate_worker = asyncio.create_task(materialize_daily_aggregates_worker())
        tasks_to_cancel.append(aggregate_worker)
        budget_worker = asyncio.create_task(budget_evaluation_worker())
        tasks_to_cancel.append(budget_worker)
        retention_worker = asyncio.create_task(retention_sweep_worker())
        tasks_to_cancel.append(retention_worker)
        if eval_scheduler is not None:
            tasks_to_cancel.append(asyncio.create_task(eval_scheduler_worker()))
        if freshness_tracker is not None:
            tasks_to_cancel.append(asyncio.create_task(freshness_worker()))

        try:
            yield
        finally:
            stop_sweeper.set()
            if job_worker is not None:
                job_worker.stop()
            for task in tasks_to_cancel:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return sync_worker, run_sync_job, check_api_health_alerts, evaluate_all_budgets, lifespan
