from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from agent_service.operations.access import ActorContext
from agent_service.operations.audit import AuditStore
from agent_service.operations.contracts import (
    DEFAULT_TIMEZONE,
    METRICS_DEFINITION_VERSION,
    OperationalEvent,
    utc_now,
)
from agent_service.operations.runtime import build_ops_runtime
from agent_service.operations.scope import (
    actor_bypasses_owner_unit_scope,
    filter_events_by_scope,
)
from agent_service.operations.settings import OpsSettings
from agent_service.operations.taxonomy import TaxonomyRepository
from agent_service.usage import convert_usd_to_twd, list_model_rates_usd, lookup_rate

from ..settings import BackofficeSettings
from .daily_aggregates import (
    FileDailyAggregateStore,
    aggregate_store_updated_at,
    aggregates_are_fresh,
    aggregates_cover_period,
    materialize_daily_aggregates,
    summarize_aggregates,
)
from .export_content import FileExportContentStore, GcsExportContentStore
from .export_format import wrap_export_payload
from .export_job_store import FileExportJobStore, FirestoreExportJobStore
from .export_service import ExportJobService
from .periods import ResolvedPeriod, event_in_period, resolve_period
from .query_budget import BudgetQueryMixin
from .query_conversations import ConversationsQueryMixin
from .query_costs import CostsQueryMixin
from .query_exports import ExportsQueryMixin
from .query_feedback import FeedbackQueryMixin
from .query_health import HealthQueryMixin
from .query_issues import IssuesQueryMixin
from .query_knowledge import KnowledgeQueryMixin
from .query_operations import OperationsQueryMixin
from .query_math import percentile as _percentile
from .usage_projection import (
    UsageDimensions,
    confirmed_zero_call,
    known_cost_total,
    project_usage,
    usage_breakdown,
)


from .query_helpers import (
    _build_issue_hierarchy,
    _is_published_knowledge_hit,
    _summarize_turn_events,
)


class BackofficeQueryService(
    OperationsQueryMixin,
    IssuesQueryMixin,
    ConversationsQueryMixin,
    CostsQueryMixin,
    HealthQueryMixin,
    BudgetQueryMixin,
    FeedbackQueryMixin,
    KnowledgeQueryMixin,
    ExportsQueryMixin,
):
    def __init__(self, settings: BackofficeSettings) -> None:
        self._settings = settings
        ops_settings = replace(
            OpsSettings.from_env(),
            enabled=True,
            store_mode=settings.ops_store_mode,
            store_path=settings.ops_store_path,
            taxonomy_path=settings.ops_taxonomy_path,
            metrics_path=settings.ops_metrics_path,
            classification_rules_path=settings.ops_classification_rules_path,
            audit_store_mode=settings.ops_audit_store_mode,
        )
        runtime = build_ops_runtime(ops_settings)
        if runtime is None:
            raise RuntimeError("Operational events are disabled.")
        self._runtime = runtime
        self._environment = ops_settings.environment
        self._metrics = json.loads(settings.ops_metrics_path.read_text(encoding="utf-8"))
        self._event_caches: dict[str, tuple[datetime, list[OperationalEvent]]] = {}
        export_store_path = settings.ops_store_path.parent / "exports"
        if settings.export_job_store_mode == "FILE":
            export_job_store = FileExportJobStore(export_store_path)
        elif settings.export_job_store_mode == "FIRESTORE":
            try:
                from google.cloud.firestore_v1.async_client import AsyncClient
            except ImportError as exc:  # pragma: no cover - optional deployment dependency
                raise RuntimeError("Firestore export jobs require google-cloud-firestore.") from exc
            firestore_client = AsyncClient(project=settings.gcp_project_id)
            export_job_store = FirestoreExportJobStore(
                firestore_client,
                settings.export_job_collection,
            )
        else:
            raise ValueError(
                f"Unsupported export job store mode: {settings.export_job_store_mode}"
            )
        if settings.export_content_backend == "FILE":
            export_content_store = FileExportContentStore(
                settings.export_content_path or export_store_path / "content"
            )
        elif settings.export_content_backend == "GCS":
            if not settings.export_gcs_bucket:
                raise ValueError("AI_OPS_EXPORT_GCS_BUCKET is required for GCS exports.")
            export_content_store = GcsExportContentStore(
                bucket_name=settings.export_gcs_bucket
            )
        else:
            raise ValueError(
                f"Unsupported export content backend: {settings.export_content_backend}"
            )
        self.export_jobs = ExportJobService(
            audit_store=self._runtime.audit_store,
            store_path=export_store_path,
            environment=ops_settings.environment,
            job_store=export_job_store,
            content_store=export_content_store,
            ttl_seconds=settings.export_ttl_seconds,
            max_records=settings.export_max_records,
            run_inline=(
                ops_settings.environment.lower() in {"dev", "test"}
                or settings.ops_store_mode == "MEMORY"
            ),
        )
        self._aggregate_store = FileDailyAggregateStore(
            settings.ops_store_path.parent / "aggregates" / "daily_ops.json"
        )

    @property
    def taxonomy(self) -> TaxonomyRepository:
        return self._runtime.taxonomy

    @property
    def audit_store(self) -> AuditStore:
        return self._runtime.audit_store

    @property
    def environment(self) -> str:
        return self._environment

    def metrics_definitions(self) -> dict[str, Any]:
        return {
            "metricsDefinitionVersion": self._metrics.get(
                "metrics_definition_version",
                METRICS_DEFINITION_VERSION,
            ),
            "pricingVersion": self._metrics.get("pricingVersion", "v1"),
            "timezone": self._metrics.get("timezone", DEFAULT_TIMEZONE),
            "usdTwdExchangeRate": float(self._metrics.get("usdTwdExchangeRate", 31.70)),
            "definitions": self._metrics.get("definitions", {}),
        }

    def _period_bounds(
        self,
        period: ResolvedPeriod | None,
    ) -> tuple[datetime | None, datetime | None]:
        if period is None:
            return None, None
        until = period.end_at if period.explicit_range else None
        return period.start_at, until

    def _cache_key(self, period: ResolvedPeriod | None) -> str:
        if period is None:
            return "all"
        if period.explicit_range:
            since = period.start_at.isoformat() if period.start_at else ""
            until = period.end_at.isoformat() if period.end_at else ""
            return f"explicit:{since}|{until}"
        window_bucket = int(utc_now().timestamp() // 30)
        return f"rolling:{period.preset}:{period.days}d:{window_bucket}"

    def _prune_cache(self, now: datetime, cache_ttl: timedelta) -> None:
        expired_keys = [
            k for k, (ts, _) in self._event_caches.items()
            if now - ts >= cache_ttl
        ]
        for k in expired_keys:
            self._event_caches.pop(k, None)
        if len(self._event_caches) >= 50:
            sorted_keys = sorted(
                self._event_caches.keys(),
                key=lambda k: self._event_caches[k][0],
            )
            for k in sorted_keys[: len(self._event_caches) - 49]:
                self._event_caches.pop(k, None)

    async def _events(
        self,
        *,
        period: ResolvedPeriod | None = None,
        force_refresh: bool = False,
    ) -> list[OperationalEvent]:
        cache_ttl = timedelta(seconds=30)
        now = utc_now()
        cache_key = self._cache_key(period)
        cached = self._event_caches.get(cache_key)
        if (
            not force_refresh
            and cached is not None
            and now - cached[0] < cache_ttl
        ):
            return list(cached[1])
        if force_refresh:
            self._event_caches.clear()
        since, until = self._period_bounds(period)
        events: list[OperationalEvent] = []
        cursor: str | None = None
        while True:
            page, cursor = await self._runtime.store.list_events(
                limit=500,
                cursor=cursor,
                since=since,
                until=until,
            )
            events.extend(page)
            if cursor is None:
                break
        self._prune_cache(now, cache_ttl)
        self._event_caches[cache_key] = (now, events)
        return events

    def _invalidate_cache(self) -> None:
        self._event_caches.clear()

    def _resolve_period(
        self,
        *,
        preset: str | None = None,
        days: int = 7,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> ResolvedPeriod:
        return resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )

    async def _scoped_events(
        self,
        actor: ActorContext,
        period: ResolvedPeriod,
        force_refresh: bool = False,
    ) -> list[OperationalEvent]:
        events = await self._events(period=period, force_refresh=force_refresh)
        in_period = [event for event in events if event_in_period(event.occurred_at, period)]
        return filter_events_by_scope(in_period, actor, self.taxonomy)

    async def purge_expired_events(self) -> dict[str, int]:
        purge = getattr(self._runtime.store, "purge_expired", None)
        if purge is None:
            return {"removed": 0}
        removed = await purge()
        self._invalidate_cache()
        return {"removed": removed}

