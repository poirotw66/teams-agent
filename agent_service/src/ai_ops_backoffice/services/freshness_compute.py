"""Freshness computation helpers for FreshnessTracker.compute_freshness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class ResolvedBacklog:
    effective_backlog_count: int | None
    effective_oldest_pending: datetime | None
    effective_has_backlog: bool | None
    backlog_is_fresh: bool


def resolve_last_sync(
    store: Any,
    *,
    resource_type: str,
    tenant_id: str | None,
    firestore_client: Any,
    last_successful_sync: dict[str, datetime],
) -> tuple[str, datetime | None]:
    if tenant_id:
        lookup_key = f"{tenant_id}:{resource_type}"
        last_sync = store.get_watermark(lookup_key)
        if last_sync is None and firestore_client is not None:
            last_sync = store.get_watermark(lookup_key, fetch_remote=True)
        return lookup_key, last_sync

    lookup_key = resource_type
    last_sync = store.get_watermark(lookup_key)
    if last_sync is None:
        norm_key = (resource_type or "").strip().lower()
        for alt in (norm_key.replace("_", "-"), norm_key.replace("-", "_")):
            if alt in last_successful_sync:
                last_sync = last_successful_sync[alt]
                break
    if last_sync is None and firestore_client is not None:
        last_sync = store.get_watermark(lookup_key, fetch_remote=True)
    return lookup_key, last_sync


def resolve_effective_watermark(
    *,
    watermark: datetime | None,
    pipeline_watermark: datetime | None,
    last_sync: datetime | None,
) -> datetime | None:
    if watermark is not None:
        return watermark
    if pipeline_watermark is not None:
        return pipeline_watermark
    if last_sync is not None:
        return last_sync
    return None


def resolve_backlog_state(
    store: Any,
    *,
    lookup_key: str,
    resource_type: str,
    tenant_id: str | None,
    firestore_client: Any,
    now_dt: datetime,
    worker_alive: bool,
    worker_stale_threshold: float,
    has_pending_backlog: bool | None,
    backlog_count: int | None,
    is_idle: bool | None,
) -> ResolvedBacklog:
    stored_backlog = store.get_backlog(lookup_key)
    if stored_backlog is None and firestore_client is not None:
        stored_backlog = store.get_backlog(lookup_key, fetch_remote=True)
    if stored_backlog is None and not tenant_id:
        stored_backlog = store.get_backlog(resource_type)

    effective_backlog_count = backlog_count
    effective_oldest_pending = None
    backlog_is_fresh = False

    if stored_backlog is not None:
        rec_at = stored_backlog.get("recorded_at")
        if rec_at is not None:
            elapsed = (now_dt - rec_at).total_seconds()
            if elapsed <= worker_stale_threshold:
                backlog_is_fresh = True
        else:
            backlog_is_fresh = worker_alive

        if effective_backlog_count is None and backlog_is_fresh:
            effective_backlog_count = stored_backlog.get("count", 0)
        if backlog_is_fresh:
            effective_oldest_pending = stored_backlog.get("oldest_pending_at")

    effective_has_backlog = has_pending_backlog
    if effective_has_backlog is None:
        if effective_backlog_count is not None:
            effective_has_backlog = effective_backlog_count > 0
        elif is_idle is True:
            effective_has_backlog = False

    return ResolvedBacklog(
        effective_backlog_count=effective_backlog_count,
        effective_oldest_pending=effective_oldest_pending,
        effective_has_backlog=effective_has_backlog,
        backlog_is_fresh=backlog_is_fresh,
    )


def compute_lag_seconds(
    *,
    now_dt: datetime,
    effective_watermark: datetime,
    backlog: ResolvedBacklog,
    is_idle: bool | None,
    backlog_lag_seconds: float | None,
) -> float:
    idle_pipeline = (
        is_idle is True
        or backlog.effective_has_backlog is False
        or (
            backlog.effective_backlog_count == 0
            and backlog.backlog_is_fresh
            and backlog.effective_has_backlog is not True
        )
    )
    if idle_pipeline:
        return 0.0
    if backlog.effective_has_backlog is True and backlog.effective_oldest_pending is not None:
        return max(0.0, (now_dt - backlog.effective_oldest_pending).total_seconds())
    if backlog_lag_seconds is not None:
        return max(0.0, backlog_lag_seconds)
    return max(0.0, (now_dt - effective_watermark).total_seconds())


def resolve_freshness_status(
    *,
    worker_alive: bool,
    is_worker_connected: bool,
    is_syncing: bool,
    lag_seconds: float,
    realtime_lag_threshold: float,
) -> Literal["REALTIME", "SYNCING", "DELAYED", "FAILED", "UNKNOWN"]:
    if not worker_alive:
        return "FAILED" if not is_worker_connected else "DELAYED"
    if is_syncing:
        return "SYNCING"
    if lag_seconds > realtime_lag_threshold:
        return "DELAYED"
    return "REALTIME"
