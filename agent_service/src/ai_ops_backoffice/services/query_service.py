from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

from knowledge_core.artifact_ports import ArtifactStorage
from operations_core.access import ActorContext
from operations_core.audit import AuditStore
from operations_core.contracts import (
    DEFAULT_TIMEZONE,
    METRICS_DEFINITION_VERSION,
    OperationalEvent,
    utc_now,
)
from operations_core.scope import filter_events_by_scope
from operations_core.settings import OpsSettings
from operations_core.taxonomy import TaxonomyRepository
from operations_core.usage import configure_pricing_provider

from ..pricing_domain import PricingService
from ..settings import BackofficeSettings
from .freshness_service import FreshnessTracker
from .periods import ResolvedPeriod, event_in_period, resolve_period
from .query_budget import BudgetQueryMixin
from .query_collaborators import (
    OpsRuntimePort,
    build_backoffice_ops_settings,
    configure_query_service_collaborators,
    resolve_ops_runtime,
)
from .query_conversations import ConversationsQueryMixin
from .query_costs import CostsQueryMixin
from .query_exports import ExportsQueryMixin
from .query_feedback import FeedbackQueryMixin
from .query_health import HealthQueryMixin
from .query_issues import IssuesQueryMixin
from .query_knowledge import KnowledgeQueryMixin
from .query_operations import OperationsQueryMixin
from .query_service_wiring import (
    build_export_job_service,
    build_freshness_tracker,
    build_pricing_service,
    build_source_trace,
)
from .source_repository import SourceRecordRepository
from .source_trace import SourceTraceResolver

__all__ = [
    "BackofficeQueryService",
    "OpsRuntimePort",
    "build_backoffice_ops_settings",
    "configure_query_service_collaborators",
]


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
    def __init__(
        self,
        settings: BackofficeSettings,
        *,
        freshness_tracker: FreshnessTracker | None = None,
        ops_runtime: OpsRuntimePort | None = None,
        artifact_storage: ArtifactStorage | None = None,
    ) -> None:
        self._settings = settings
        self._knowledge_identity_token: tuple[float, str] | None = None
        self._knowledge_identity_token_lock = asyncio.Lock()
        ops_settings = build_backoffice_ops_settings(settings)
        runtime = resolve_ops_runtime(
            ops_settings,
            freshness_tracker=freshness_tracker,
            ops_runtime=ops_runtime,
        )
        self._runtime = runtime
        self._environment = ops_settings.environment
        self._source_trace = build_source_trace(settings, artifact_storage=artifact_storage)
        self._freshness_tracker = build_freshness_tracker(
            settings, runtime=runtime, freshness_tracker=freshness_tracker
        )
        self._revoked_principals_loader: Callable[[], set[str]] | None = None
        self._metrics = json.loads(settings.ops_metrics_path.read_text(encoding="utf-8"))
        self._event_caches: dict[str, tuple[datetime, list[OperationalEvent]]] = {}
        self._event_cache_lock = asyncio.Lock()
        self.export_jobs = build_export_job_service(
            settings, runtime=runtime, environment=ops_settings.environment
        )
        (
            self._pricing_repository,
            self._pricing_service,
            self._aggregate_store,
        ) = build_pricing_service(
            settings, runtime=runtime, environment=self._environment
        )
        configure_pricing_provider(self._pricing_service)

    @property
    def pricing_service(self) -> PricingService:
        return self._pricing_service

    @property
    def taxonomy(self) -> TaxonomyRepository:
        return self._runtime.taxonomy

    @property
    def audit_store(self) -> AuditStore:
        return self._runtime.audit_store

    @property
    def environment(self) -> str:
        return self._environment

    @property
    def source_trace(self) -> SourceTraceResolver:
        """Public accessor for citation/source resolution used by routers."""
        return self._source_trace

    @property
    def runtime_settings(self) -> OpsSettings:
        """Public accessor for the ops runtime settings used at wiring time."""
        return self._runtime.settings

    @property
    def source_repository(self) -> SourceRecordRepository:
        """Public accessor for the source-record store used by quality and sources routes."""
        return self._source_trace.source_repository

    def metrics_definitions(self) -> dict[str, Any]:
        pricing_svc = self._pricing_service
        pricing_version = (
            pricing_svc.get_pricing_version()
            if pricing_svc is not None
            else str(self._metrics.get("pricingVersion", "v1"))
        )
        exchange_rate = (
            pricing_svc.get_exchange_rate()
            if pricing_svc is not None
            else float(self._metrics.get("usdTwdExchangeRate", 31.70))
        )
        # HistoricalPricingRule versions stamp both model rates and FX together.
        exchange_rate_version = pricing_version
        return {
            "metricsDefinitionVersion": self._metrics.get(
                "metrics_definition_version",
                METRICS_DEFINITION_VERSION,
            ),
            "pricingVersion": pricing_version,
            "exchangeRateVersion": exchange_rate_version,
            "timezone": self._metrics.get("timezone", DEFAULT_TIMEZONE),
            "usdTwdExchangeRate": float(exchange_rate),
            "definitions": self._metrics.get("definitions", {}),
        }

    async def record_component_usage(
        self,
        *,
        component: str,
        status: str = "SUCCESS",
        elapsed_ms: float | None = None,
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        """Append a synthetic usage.recorded event for health telemetry producers."""
        timestamp = occurred_at or utc_now()
        event_payload: dict[str, Any] = {
            "component": component,
            "status": status,
            **(payload or {}),
        }
        if "attributionScope" not in event_payload:
            event_payload["attributionScope"] = "HEALTH_TELEMETRY"
        if elapsed_ms is not None:
            event_payload["elapsedMs"] = elapsed_ms
        event = OperationalEvent(
            event_id=f"health:{component}:{correlation_id or timestamp.isoformat()}",
            event_type="usage.recorded",
            occurred_at=timestamp,
            environment=self._environment,  # type: ignore[arg-type]
            correlation_id=correlation_id or f"health-{component}",
            payload=event_payload,
        )
        await self._runtime.store.append(event)
        self._invalidate_cache()

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
        bucket_seconds = max(1, self._settings.query_cache_ttl_seconds)
        window_bucket = int(utc_now().timestamp() // bucket_seconds)
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
        cache_ttl = timedelta(seconds=self._settings.query_cache_ttl_seconds)
        now = utc_now()
        cache_key = self._cache_key(period)
        cached = self._event_caches.get(cache_key)
        if (
            not force_refresh
            and cached is not None
            and now - cached[0] < cache_ttl
        ):
            return list(cached[1])
        async with self._event_cache_lock:
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
            return list(events)

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

    async def scoped_events(
        self,
        actor: ActorContext,
        period: ResolvedPeriod,
        force_refresh: bool = False,
    ) -> list[OperationalEvent]:
        """Public accessor for scope-filtered events used by reconciliation and mixins."""
        return await self._scoped_events(
            actor, period, force_refresh=force_refresh
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

    def bind_revocation_lookup(self, loader: Callable[[], set[str]]) -> None:
        """Bind authoritative revoked-principal lookup used by request auth (F02/A04)."""
        self._revoked_principals_loader = loader

    def is_principal_revoked(self, user_id: str, tenant_id: str | None = None) -> bool:
        """Return True when the principal is revoked in governance state."""
        del tenant_id  # reserved for future tenant-scoped revocation lists
        loader = self._revoked_principals_loader
        if loader is None:
            return False
        return str(user_id) in {str(item) for item in (loader() or set())}

    def resolve_source_content_excerpt(
        self,
        source_ref_id: str,
        *,
        max_chars: int = 2400,
    ) -> str | None:
        """Return a truncated content excerpt for a source ref, if resolvable."""
        try:
            source = self._source_trace.resolve_source_ref(source_ref_id)
        except Exception:
            return None
        if source is None or not source.content:
            return None
        return source.content[:max_chars]
