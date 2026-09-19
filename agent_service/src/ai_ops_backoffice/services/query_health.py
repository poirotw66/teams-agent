"""Health probes and summary queries for the AI Ops backoffice."""

from __future__ import annotations

from typing import Any

from operations_core.contracts import utc_now

from .query_health_probes import HealthProbeMixin
from .query_health_summary import (
    apply_historical_statuses,
    build_monitoring_links,
    build_raw_components,
    is_historical_target,
)
from .query_health_telemetry import compute_health_telemetry
from .query_health_window import resolve_taipei_day_window

__all__ = [
    "HealthQueryMixin",
    "HealthQueryService",
    "resolve_taipei_day_window",
]


class HealthQueryMixin(HealthProbeMixin):
    """Mixin providing system-health query helpers for BackofficeQueryService."""

    async def _health_telemetry(
        self,
        target_date: str | None = None,
    ) -> tuple[
        dict[str, dict[str, Any]],
        list[dict[str, Any]],
        Any,
        Any,
        dict[str, Any],
    ]:
        return await compute_health_telemetry(self._events, target_date=target_date)

    async def health_summary(self, target_date: str | None = None) -> dict[str, Any]:
        agent = await self._probe_url(self._settings.agent_api_url)
        agent_functional = await self._probe_agent_functional(self._settings.agent_api_url)
        internal_portal = (
            self._settings.knowledge_internal_url or self._settings.knowledge_portal_url
        )
        portal = await self._probe_url(internal_portal)
        knowledge_release = await self._probe_knowledge_release(internal_portal)
        adapter = await self._probe_url(self._settings.adapter_api_url)
        ticket = await self._probe_url(self._settings.ticket_service_url, path="/healthz")

        (
            telemetry,
            recent_anomalies,
            _window_start,
            _window_end,
            monitoring_scope,
        ) = await self._health_telemetry(target_date=target_date)
        retrieval = dict(agent_functional)
        if self._settings.simulate_health_anomalies:
            agent = {"status": "DEGRADED", "note": "Simulated LLM API latency spike."}
            retrieval = {"status": "DOWN", "note": "Simulated RAG index unreachable."}
            ticket = {"status": "DOWN", "note": "Simulated Ticket API timeout."}

        is_historical = is_historical_target(target_date)
        raw_components = build_raw_components(
            agent=agent,
            agent_functional=agent_functional,
            adapter=adapter,
            portal=portal,
            knowledge_release=knowledge_release,
            ticket=ticket,
            retrieval=retrieval,
            telemetry=telemetry,
            monitoring_scope=monitoring_scope,
            ops_store_mode=self._settings.ops_store_mode,
        )
        components = apply_historical_statuses(
            raw_components,
            is_historical=is_historical,
            target_date=target_date,
        )
        return {
            "components": components,
            "targetDate": target_date,
            "isHistorical": is_historical,
            "historicalNotice": (
                f"您正在檢視歷史日期（{target_date}）之遙測資料。"
                "狀態欄依當日遙測判定，即時探測狀態僅代表當前連線狀態。"
                if is_historical
                else None
            ),
            "telemetryWindowHours": 24 if not target_date else None,
            "monitoringScope": monitoring_scope,
            "recentAnomalies": recent_anomalies,
            "monitoringLinks": build_monitoring_links(self._settings.gcp_project_id),
            "simulatedAnomalies": self._settings.simulate_health_anomalies,
            "updatedAt": utc_now().isoformat(),
        }


HealthQueryService = HealthQueryMixin

