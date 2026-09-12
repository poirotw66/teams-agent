from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from .contracts import FreshnessRecorder, OperationalEvent, utc_now
from .masking import redact_secrets
from .policy_runtime import active_masking_policy_version
from .retention import retention_expiry
from .settings import OpsSettings


class OperationalStore(Protocol):
    async def append(self, event: OperationalEvent) -> bool: ...

    async def find_events(self, *, correlation_id: str) -> list[OperationalEvent]:
        ...

    async def list_events(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[OperationalEvent], str | None]: ...


class EventIngestionService:
    def __init__(
        self,
        store: OperationalStore,
        settings: OpsSettings,
        freshness_tracker: FreshnessRecorder | None = None,
        backlog_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._freshness_tracker = freshness_tracker
        self._backlog_provider = backlog_provider

    @property
    def freshness_recorder(self) -> FreshnessRecorder | None:
        return self._freshness_tracker

    async def _resolve_backlog(self) -> tuple[int, datetime | None] | None:
        """Resolve genuine backlog count and oldest timestamp from real queue or provider."""
        if self._backlog_provider is not None:
            res = self._backlog_provider()
            if asyncio.iscoroutine(res):
                res = await res
            if isinstance(res, tuple) and len(res) == 2:
                return (int(res[0]), res[1])
            if isinstance(res, (int, float)):
                return (int(res), None)
            if isinstance(res, dict):
                return (int(res.get("count", res.get("pending", 0))), res.get("oldest_pending_at"))
        if hasattr(self._store, "get_backlog_stats"):
            res = self._store.get_backlog_stats()
            if asyncio.iscoroutine(res):
                res = await res
            if isinstance(res, dict):
                return (int(res.get("count", res.get("pending", 0))), res.get("oldest_pending_at"))
        return None

    async def ingest(self, event: OperationalEvent) -> bool:
        # This is the persistence boundary.  Emitters should mask at source, but
        # every event is defensively normalised here before any store receives it.
        # redact_secrets is idempotent, preserving retry/idempotency semantics.
        payload = redact_secrets(event.payload)
        active_policy = active_masking_policy_version()
        source_policy_version = event.masking_policy_version
        source_payload_policy = event.payload.get("maskingPolicyVersion")
        if (
            source_policy_version == active_policy
            and isinstance(source_payload_policy, str)
            and source_payload_policy != active_policy
        ):
            source_policy_version = source_payload_policy
        if source_policy_version != active_policy:
            payload["sourceMaskingPolicyVersion"] = source_policy_version
        # The persisted copy was cleaned at this boundary, irrespective of an
        # older producer's policy.  Keep the source version above for replay
        # provenance; this does not alter events already stored elsewhere.
        payload["maskingPolicyVersion"] = active_policy
        event = event.model_copy(
            update={
                "ingested_at": event.ingested_at or utc_now(),
                "environment": event.environment or self._settings.environment,  # type: ignore[arg-type]
                "retention_expires_at": event.retention_expires_at
                or retention_expiry(self._settings),
                "masking_policy_version": active_policy,
                "payload": payload,
            }
        )
        persisted = await self._store.append(event)
        if persisted and self._freshness_tracker is not None:
            tenant_id = getattr(event, "tenant_id", None)
            ingested_at = event.ingested_at or utc_now()
            if hasattr(self._freshness_tracker, "record_stage_event"):
                self._freshness_tracker.record_stage_event(
                    correlation_id=event.correlation_id,
                    stage="EVENT_INGESTED",
                    at=ingested_at,
                    tenant_id=tenant_id,
                )
                self._freshness_tracker.record_stage_event(
                    correlation_id="conversations",
                    stage="EVENT_INGESTED",
                    at=ingested_at,
                    tenant_id=tenant_id,
                )
            if hasattr(self._freshness_tracker, "record_sync_success"):
                self._freshness_tracker.record_sync_success(
                    resource_type="conversations",
                    at=ingested_at,
                    tenant_id=tenant_id,
                )
            if hasattr(self._freshness_tracker, "record_backlog"):
                real_backlog = await self._resolve_backlog()
                if real_backlog is not None:
                    count, oldest_at = real_backlog
                    self._freshness_tracker.record_backlog(
                        resource_type="conversations",
                        backlog_count=count,
                        oldest_pending_at=oldest_at,
                        at=ingested_at,
                        tenant_id=tenant_id,
                    )
        return persisted

    async def ingest_many(self, events: list[OperationalEvent]) -> int:
        inserted = 0
        for event in events:
            if await self.ingest(event):
                inserted += 1
        return inserted

    async def find_events(self, *, correlation_id: str) -> list[OperationalEvent]:
        return await self._store.find_events(correlation_id=correlation_id)
