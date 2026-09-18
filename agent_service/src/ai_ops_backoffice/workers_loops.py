"""Periodic background loop coroutines for AI Ops lifespan workers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from operations_core.access import ActorContext

from .workers_retention import run_scheduled_retention_sweep

logger = logging.getLogger(__name__)

__all__ = [
    "budget_evaluation_loop",
    "eval_scheduler_loop",
    "export_purge_loop",
    "freshness_loop",
    "materialize_daily_aggregates_loop",
    "retention_sweep_loop",
]


async def export_purge_loop(*, stop_event: asyncio.Event, query_service) -> None:
    while not stop_event.is_set():
        try:
            await query_service.export_jobs.purge_expired_jobs()
        except Exception:
            logger.exception("Failed to purge expired export jobs.")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except TimeoutError:
            continue


async def materialize_daily_aggregates_loop(
    *,
    stop_event: asyncio.Event,
    query_service,
    freshness_tracker,
) -> None:
    # Warm aggregates shortly after boot, then refresh periodically so
    # operations_summary can prefer aggregate rows when coverage is complete.
    first_delay_seconds = 5
    refresh_interval_seconds = 300
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=first_delay_seconds)
        return
    except TimeoutError:
        pass
    while not stop_event.is_set():
        try:
            result = await query_service.rebuild_daily_aggregates(days=30)
            logger.info(
                "Materialized daily aggregates written=%s days=%s",
                result.get("written"),
                len(result.get("days") or []),
            )
            if freshness_tracker is not None:
                _record_aggregate_freshness(freshness_tracker)
        except Exception:
            logger.exception("Failed to materialize daily aggregates.")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=refresh_interval_seconds)
        except TimeoutError:
            continue


def _record_aggregate_freshness(freshness_tracker) -> None:
    freshness_tracker.record_sync_success("reporting")
    freshness_tracker.record_sync_success("daily_aggregates")
    freshness_tracker.record_sync_success("operations_overview")
    freshness_tracker.record_sync_success("operations-overview")
    freshness_tracker.record_stage_event("operations_overview", "AGGREGATION_COMPLETED")
    freshness_tracker.record_stage_event("operations-overview", "AGGREGATION_COMPLETED")


async def budget_evaluation_loop(
    *,
    stop_event: asyncio.Event,
    resolved_settings,
    sync_worker: ActorContext,
    evaluate_all_budgets: Callable[[ActorContext], Awaitable[dict[str, Any]]],
) -> None:
    first_delay_seconds = 5
    interval_seconds = resolved_settings.budget_eval_interval_seconds
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=first_delay_seconds)
        return
    except TimeoutError:
        pass
    while not stop_event.is_set():
        try:
            res = await evaluate_all_budgets(sync_worker)
            logger.info("Auto budget & anomaly evaluation completed: %s", res)
        except Exception:
            logger.exception("Failed to run auto budget evaluation.")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


async def retention_sweep_loop(
    *,
    stop_event: asyncio.Event,
    resolved_settings,
    sync_worker: ActorContext,
    query_service,
    sync_service,
    budget_service,
    example_service,
    quality_service,
    governance_service,
) -> None:
    first_delay_seconds = 10
    interval_seconds = getattr(resolved_settings, "retention_eval_interval_seconds", 3600)
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=first_delay_seconds)
        return
    except TimeoutError:
        pass
    while not stop_event.is_set():
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
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


async def eval_scheduler_loop(
    *,
    stop_event: asyncio.Event,
    resolved_settings,
    eval_scheduler,
) -> None:
    first_delay_seconds = 5
    interval_seconds = getattr(resolved_settings, "eval_schedule_interval_seconds", 60)
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=first_delay_seconds)
        return
    except TimeoutError:
        pass
    while not stop_event.is_set():
        try:
            dispatched = eval_scheduler.scan_and_dispatch_due_schedules()
            if dispatched:
                logger.info(
                    "Evaluation scheduler dispatched %s due schedules",
                    len(dispatched),
                )
        except Exception:
            logger.exception("Failed to scan and dispatch due evaluation schedules.")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


async def freshness_loop(
    *,
    stop_event: asyncio.Event,
    resolved_settings,
    query_service,
    sync_service,
    freshness_tracker,
) -> None:
    first_delay_seconds = 10
    interval_seconds = getattr(resolved_settings, "freshness_eval_interval_seconds", 300)
    # Keep tracker stale threshold aligned with the heartbeat cadence.
    if freshness_tracker is not None:
        freshness_tracker._heartbeat_interval = float(interval_seconds)
        freshness_tracker._worker_stale_threshold = float(interval_seconds) * 2
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=first_delay_seconds)
        return
    except TimeoutError:
        pass
    while not stop_event.is_set():
        try:
            await _record_freshness_backlog(
                query_service=query_service,
                sync_service=sync_service,
                freshness_tracker=freshness_tracker,
            )
        except Exception:
            logger.exception("Failed to record worker heartbeat and backlog for freshness.")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


async def _record_freshness_backlog(
    *,
    query_service,
    sync_service,
    freshness_tracker,
) -> None:
    freshness_tracker.record_worker_heartbeat()
    now_val = freshness_tracker.now()

    conv_backlog = 0
    conv_oldest = None
    if hasattr(query_service, "_runtime") and hasattr(query_service._runtime, "store"):
        store = query_service._runtime.store
        if hasattr(store, "get_backlog_stats"):
            stats = await store.get_backlog_stats()
            conv_backlog = stats.get("count", stats.get("pending", 0))
            conv_oldest = stats.get("oldest_pending_at")

    export_backlog = 0
    if hasattr(query_service, "export_jobs") and hasattr(query_service.export_jobs, "list_jobs"):
        try:
            queued_exports = await query_service.export_jobs.list_jobs(status="QUEUED")
            export_backlog = len(queued_exports) if queued_exports else 0
        except Exception:
            export_backlog = 0

    sync_backlog = 0
    if sync_service is not None and hasattr(sync_service, "get_pending_job_count"):
        try:
            sync_backlog = await sync_service.get_pending_job_count()
        except Exception:
            sync_backlog = 0

    freshness_tracker.record_backlog(
        "conversations",
        backlog_count=conv_backlog,
        oldest_pending_at=conv_oldest,
        at=now_val,
    )
    freshness_tracker.record_backlog(
        "reporting",
        backlog_count=export_backlog,
        at=now_val,
    )
    freshness_tracker.record_backlog(
        "operations_overview",
        backlog_count=max(conv_backlog, sync_backlog),
        at=now_val,
    )
