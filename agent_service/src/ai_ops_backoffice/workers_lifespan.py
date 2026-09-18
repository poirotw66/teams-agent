"""FastAPI lifespan wiring for AI Ops background workers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI

from operations_core.access import ActorContext

from .workers_loops import (
    budget_evaluation_loop,
    eval_scheduler_loop,
    export_purge_loop,
    freshness_loop,
    materialize_daily_aggregates_loop,
    retention_sweep_loop,
)

logger = logging.getLogger(__name__)

__all__ = ["build_lifespan"]

BudgetEvaluator = Callable[[ActorContext], Awaitable[dict[str, Any]]]


def build_lifespan(
    *,
    resolved_settings,
    query_service,
    sync_service,
    budget_service,
    example_service,
    quality_service,
    governance_service,
    job_worker,
    eval_scheduler,
    freshness_tracker,
    sync_worker: ActorContext,
    evaluate_all_budgets: BudgetEvaluator,
):
    """Return the FastAPI lifespan context manager for background workers."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
        await _recover_interrupted_exports(query_service)

        if job_worker is not None:
            job_worker.start()

        tasks_to_cancel = _spawn_background_tasks(
            stop_event=stop_sweeper,
            resolved_settings=resolved_settings,
            query_service=query_service,
            sync_service=sync_service,
            budget_service=budget_service,
            example_service=example_service,
            quality_service=quality_service,
            governance_service=governance_service,
            eval_scheduler=eval_scheduler,
            freshness_tracker=freshness_tracker,
            sync_worker=sync_worker,
            evaluate_all_budgets=evaluate_all_budgets,
        )

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

    return lifespan


async def _recover_interrupted_exports(query_service) -> None:
    try:
        recovered = await query_service.export_jobs.recover_interrupted_jobs()
        if recovered:
            logger.info("Recovered %s interrupted export jobs", recovered)
    except Exception:
        logger.exception("Failed to recover interrupted export jobs.")


def _spawn_background_tasks(
    *,
    stop_event: asyncio.Event,
    resolved_settings,
    query_service,
    sync_service,
    budget_service,
    example_service,
    quality_service,
    governance_service,
    eval_scheduler,
    freshness_tracker,
    sync_worker: ActorContext,
    evaluate_all_budgets: BudgetEvaluator,
) -> list[asyncio.Task]:
    tasks: list[asyncio.Task] = [
        asyncio.create_task(export_purge_loop(stop_event=stop_event, query_service=query_service)),
        asyncio.create_task(query_service.export_jobs.run_recovery_scanner(stop_event)),
        asyncio.create_task(
            materialize_daily_aggregates_loop(
                stop_event=stop_event,
                query_service=query_service,
                freshness_tracker=freshness_tracker,
            )
        ),
        asyncio.create_task(
            budget_evaluation_loop(
                stop_event=stop_event,
                resolved_settings=resolved_settings,
                sync_worker=sync_worker,
                evaluate_all_budgets=evaluate_all_budgets,
            )
        ),
        asyncio.create_task(
            retention_sweep_loop(
                stop_event=stop_event,
                resolved_settings=resolved_settings,
                sync_worker=sync_worker,
                query_service=query_service,
                sync_service=sync_service,
                budget_service=budget_service,
                example_service=example_service,
                quality_service=quality_service,
                governance_service=governance_service,
            )
        ),
    ]
    if eval_scheduler is not None:
        tasks.append(
            asyncio.create_task(
                eval_scheduler_loop(
                    stop_event=stop_event,
                    resolved_settings=resolved_settings,
                    eval_scheduler=eval_scheduler,
                )
            )
        )
    if freshness_tracker is not None:
        tasks.append(
            asyncio.create_task(
                freshness_loop(
                    stop_event=stop_event,
                    resolved_settings=resolved_settings,
                    query_service=query_service,
                    sync_service=sync_service,
                    freshness_tracker=freshness_tracker,
                )
            )
        )
    return tasks
