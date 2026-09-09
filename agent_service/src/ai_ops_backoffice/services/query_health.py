"""Health probes and summary queries for the AI Ops backoffice."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from agent_service.operations.contracts import utc_now

from .query_math import percentile as _percentile
from .usage_projection import project_usage


class HealthQueryMixin:
    """Mixin providing system-health query helpers for BackofficeQueryService."""

    async def _probe_url(self, url: str | None, path: str = "/healthz") -> dict[str, str]:
        if not url:
            return {"status": "UNKNOWN", "note": "URL not configured."}
        target = f"{url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(target)
            if response.status_code < 400:
                return {"status": "READY", "note": f"HTTP {response.status_code}"}
            return {"status": "DEGRADED", "note": f"HTTP {response.status_code}"}
        except httpx.HTTPError as exc:
            return {"status": "DOWN", "note": str(exc)}


    async def _probe_agent_functional(self, url: str | None) -> dict[str, str]:
        if not url:
            return {"status": "UNKNOWN", "note": "Agent API URL not configured."}
        target = f"{url.rstrip('/')}/healthz"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(target)
            if response.status_code >= 400:
                return {"status": "DEGRADED", "note": f"HTTP {response.status_code}"}
            payload = response.json()
            retrieval = str(payload.get("retrieval") or "")
            chunks = int(payload.get("chunks") or 0)
            if retrieval and chunks > 0:
                return {
                    "status": "READY",
                    "note": f"retrieval={retrieval}, chunks={chunks}",
                }
            return {"status": "DEGRADED", "note": "Agent health ok but retrieval index is empty."}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {"status": "DOWN", "note": str(exc)}


    async def _probe_retrieval_search(self, url: str | None) -> dict[str, str]:
        if not url:
            return {"status": "UNKNOWN", "note": "Agent API URL not configured."}
        target = f"{url.rstrip('/')}/retrieval/search"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(
                    target,
                    json={"query": "vpn", "limit": 1, "groups": []},
                )
            if response.status_code == 401:
                return {"status": "READY", "note": "Retrieval endpoint reachable (auth required)."}
            if response.status_code >= 400:
                return {"status": "DEGRADED", "note": f"HTTP {response.status_code}"}
            hits = response.json().get("hits") or []
            return {"status": "READY", "note": f"hits={len(hits)}"}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {"status": "DOWN", "note": str(exc)}


    async def _probe_knowledge_release(self, url: str | None) -> dict[str, Any]:
        if not url:
            return {
                "status": "UNKNOWN",
                "note": "Knowledge Portal URL not configured.",
                "releaseId": None,
                "publishedAt": None,
                "indexStatus": "UNKNOWN",
                "documentCount": 0,
            }
        headers = {
            "X-Portal-User-Id": "ai-ops-backoffice",
            "X-Portal-User-Name": "AI%20Ops%20Backoffice",
            "X-Portal-Role": "PLATFORM",
            "X-Portal-Owner-Units": self._settings.default_owner_unit_id,
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"{url.rstrip('/')}/api/releases",
                    headers=headers,
                )
            if response.status_code >= 400:
                return {
                    "status": "DOWN",
                    "note": f"Portal returned HTTP {response.status_code}",
                    "releaseId": None,
                    "publishedAt": None,
                    "indexStatus": "UNKNOWN",
                    "documentCount": 0,
                }
            payload = response.json()
            releases = payload.get("items") if isinstance(payload, dict) else payload
            releases = [item for item in (releases or []) if isinstance(item, dict)]
            active = next(
                (item for item in releases if item.get("status") == "ACTIVE"),
                None,
            )
            if active is None:
                return {
                    "status": "DEGRADED",
                    "note": "No active Knowledge release.",
                    "releaseId": None,
                    "publishedAt": None,
                    "indexStatus": "NOT_ACTIVE",
                    "documentCount": 0,
                }
            return {
                "status": "READY",
                "note": "Active Knowledge release is available.",
                "releaseId": active.get("release_id"),
                "publishedAt": active.get("activated_at") or active.get("created_at"),
                "indexStatus": "READY",
                "documentCount": len(active.get("manifest") or []),
                "indexSettingVersion": active.get("index_setting_version"),
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {
                "status": "DOWN",
                "note": str(exc),
                "releaseId": None,
                "publishedAt": None,
                "indexStatus": "UNKNOWN",
                "documentCount": 0,
            }

    @staticmethod


    def _health_metric_summary(
        samples: list[tuple[str, float | None]],
    ) -> dict[str, Any]:
        if not samples:
            return {
                "telemetryStatus": "NO_DATA",
                "requestCount": 0,
                "availabilityRate": None,
                "errorRate": None,
                "timeoutRate": None,
                "p50LatencyMs": None,
                "p95LatencyMs": None,
            }
        statuses = [status.upper() for status, _ in samples]
        latencies = [latency for _, latency in samples if latency is not None]
        failures = sum(status == "FAILED" for status in statuses)
        timeouts = sum(status == "TIMEOUT" for status in statuses)
        successful = len(samples) - failures - timeouts
        return {
            "telemetryStatus": "AVAILABLE",
            "requestCount": len(samples),
            "availabilityRate": round(successful / len(samples), 4),
            "errorRate": round(failures / len(samples), 4),
            "timeoutRate": round(timeouts / len(samples), 4),
            "p50LatencyMs": _percentile(latencies, 0.5),
            "p95LatencyMs": _percentile(latencies, 0.95),
        }


    async def _health_telemetry(
        self,
        target_date: str | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        if target_date:
            try:
                dt = datetime.fromisoformat(target_date)
                window_start = dt.replace(
                    hour=0, minute=0, second=0, microsecond=0,
                    tzinfo=UTC if dt.tzinfo is None else dt.tzinfo,
                )
                window_end = window_start + timedelta(days=1)
                events = [
                    event for event in await self._events()
                    if window_start <= event.occurred_at < window_end
                ]
            except Exception:
                window_start = utc_now() - timedelta(hours=24)
                events = [
                    event for event in await self._events()
                    if event.occurred_at >= window_start
                ]
        else:
            window_start = utc_now() - timedelta(hours=24)
            events = [
                event for event in await self._events()
                if event.occurred_at >= window_start
            ]
        failures = [event for event in events if event.event_type == "request.failed"]
        anomalies = [
            {
                "occurredAt": event.occurred_at.isoformat(),
                "component": str(event.payload.get("component") or "agent-service"),
                "status": "TIMEOUT"
                if "timeout" in json.dumps(event.payload).lower()
                else "FAILED",
                "errorType": event.payload.get("errorType")
                or event.payload.get("errorCode")
                or "REQUEST_FAILED",
                "correlationId": event.correlation_id,
            }
            for event in failures
        ]
        request_latencies = {
            event.request_id or event.turn_id or event.correlation_id: float(
                event.payload["elapsedMs"]
            )
            for event in project_usage(events).request_latency_events
            if event.payload.get("elapsedMs") is not None
        }
        agent_samples: list[tuple[str, float | None]] = []
        for turn in (event for event in events if event.event_type == "turn.received"):
            failure = next(
                (
                    item for item in failures
                    if any(
                        (
                            bool(turn.request_id and item.request_id == turn.request_id),
                            bool(turn.turn_id and item.turn_id == turn.turn_id),
                            item.correlation_id == turn.correlation_id,
                        )
                    )
                ),
                None,
            )
            failure_text = json.dumps(failure.payload).lower() if failure else ""
            status = "TIMEOUT" if "timeout" in failure_text else "FAILED" if failure else "SUCCESS"
            request_key = turn.request_id or turn.turn_id or turn.correlation_id
            agent_samples.append((status, request_latencies.get(request_key)))

        usage_samples: list[tuple[str, str, float | None]] = []
        for event in events:
            if event.event_type != "usage.recorded":
                continue
            scope = str(event.payload.get("attributionScope") or "LEGACY")
            if scope == "REQUEST_SUMMARY":
                continue
            elapsed = event.payload.get("elapsedMs")
            usage_samples.append(
                (
                    str(event.payload.get("component") or "unknown"),
                    str(event.payload.get("status") or "SUCCESS"),
                    float(elapsed) if elapsed is not None else None,
                )
            )
            usage_status = str(event.payload.get("status") or "SUCCESS").upper()
            if usage_status in {"FAILED", "TIMEOUT"}:
                anomalies.append(
                    {
                        "occurredAt": event.occurred_at.isoformat(),
                        "component": str(event.payload.get("component") or "unknown"),
                        "status": usage_status,
                        "errorType": event.payload.get("errorType")
                        or event.payload.get("errorCode")
                        or "UPSTREAM_FAILURE",
                        "correlationId": event.correlation_id,
                    }
                )

        def usage_for(prefixes: tuple[str, ...]) -> list[tuple[str, float | None]]:
            return [
                (status, latency)
                for component, status, latency in usage_samples
                if component.startswith(prefixes)
            ]

        faq_samples = [
            ("SUCCESS", None)
            for event in events
            if event.event_type == "faq.answered"
        ]
        ticket_samples = [
            (
                "TIMEOUT"
                if "timeout" in json.dumps(event.payload).lower()
                else "FAILED" if event.event_type == "ticket.failed" else "SUCCESS",
                None,
            )
            for event in events
            if event.event_type in {"ticket.created", "ticket.failed"}
        ]
        adapter_usage = usage_for(("teams_", "adapter_", "teams-adapter", "teams_bot"))
        teams_events = [
            ("SUCCESS", request_latencies.get(event.request_id or event.turn_id or event.correlation_id))
            for event in events
            if event.event_type in {"adapter.turn_received", "teams.message_received", "teams.inbound"}
        ]
        teams_samples = adapter_usage + teams_events
        index_samples = usage_for(
            ("knowledge_index", "indexer", "index", "retrieval_index", "embedding")
        )

        all_usage = [(status, latency) for _, status, latency in usage_samples]
        telemetry = {
            "teams-adapter": self._health_metric_summary(teams_samples),
            "agent-service": self._health_metric_summary(agent_samples),
            "llm-api": self._health_metric_summary(all_usage),
            "issue-extractor": self._health_metric_summary(
                usage_for(("issue_extractor",))
            ),
            "faq-service": self._health_metric_summary(faq_samples),
            "agent-retrieval-index": self._health_metric_summary(index_samples),
            "agent-retrieval-search": self._health_metric_summary(
                usage_for(("knowledge_", "gemini_file_search"))
            ),
            "ticket-service": self._health_metric_summary(ticket_samples),
        }
        anomalies.sort(key=lambda item: item["occurredAt"], reverse=True)
        return telemetry, anomalies[:10]


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

        telemetry, recent_anomalies = await self._health_telemetry(target_date=target_date)
        no_telemetry = self._health_metric_summary([])
        retrieval = dict(agent_functional)
        if self._settings.simulate_health_anomalies:
            agent = {"status": "DEGRADED", "note": "Simulated LLM API latency spike."}
            retrieval = {"status": "DOWN", "note": "Simulated RAG index unreachable."}
            ticket = {"status": "DOWN", "note": "Simulated Ticket API timeout."}

        is_historical = False
        if target_date:
            try:
                parsed_target = datetime.strptime(target_date, "%Y-%m-%d").date()
                is_historical = parsed_target < utc_now().date()
            except ValueError:
                pass

        raw_components = [
            {"id": "agent-service", **agent, **telemetry["agent-service"]},
            {"id": "agent-functional", **agent_functional, **no_telemetry},
            {"id": "teams-adapter", **adapter, **telemetry["teams-adapter"]},
            {
                "id": "agent-retrieval-index",
                "status": knowledge_release.get("indexStatus") or agent_functional.get("status", "UNKNOWN"),
                "note": knowledge_release.get("note") or agent_functional.get("note"),
                **telemetry["agent-retrieval-index"],
            },
            {
                "id": "agent-retrieval-search",
                **retrieval,
                **telemetry["agent-retrieval-search"],
            },
            {
                "id": "llm-api",
                **agent,
                **telemetry["llm-api"],
            },
            {
                "id": "issue-extractor",
                **agent,
                **telemetry["issue-extractor"],
            },
            {"id": "faq-service", **agent, **telemetry["faq-service"]},
            {
                "id": "analytics-store",
                "status": "READY",
                "note": f"mode={self._settings.ops_store_mode}",
                **no_telemetry,
            },
            {"id": "knowledge-portal", **portal, **no_telemetry},
            {"id": "knowledge-release", **knowledge_release, **no_telemetry},
            {"id": "ticket-service", **ticket, **telemetry["ticket-service"]},
        ]

        components: list[dict[str, Any]] = []
        for comp in raw_components:
            live_status = str(comp.get("status") or "UNKNOWN")
            live_note = comp.get("note")
            if is_historical:
                telem_status = comp.get("telemetryStatus")
                avail_rate = comp.get("availabilityRate")
                err_rate = comp.get("errorRate") or 0.0
                timeout_rate = comp.get("timeoutRate") or 0.0
                req_count = comp.get("requestCount") or 0

                if telem_status == "AVAILABLE" and req_count > 0:
                    if err_rate == 0.0 and timeout_rate == 0.0:
                        hist_status = "READY"
                    elif avail_rate == 0.0:
                        hist_status = "DOWN"
                    else:
                        hist_status = "DEGRADED"
                    hist_note = f"依歷史遙測判定 ({target_date})"
                else:
                    hist_status = "NO_DATA"
                    hist_note = f"歷史日期無遙測紀錄；即時探測為 {live_status}"

                components.append({
                    **comp,
                    "status": hist_status,
                    "liveProbeStatus": live_status,
                    "liveProbeNote": live_note,
                    "isHistorical": True,
                    "note": hist_note,
                })
            else:
                components.append(comp)

        monitoring_links: dict[str, str] = {}
        project_id = self._settings.gcp_project_id
        if project_id:
            monitoring_links["cloudMonitoring"] = (
                f"https://console.cloud.google.com/monitoring/dashboards"
                f"?project={project_id}"
            )
            monitoring_links["cloudLogging"] = (
                f"https://console.cloud.google.com/logs/query;query=resource.type%3D"
                f"%22cloud_run_revision%22%0Aseverity%3E%3DERROR;"
                f"?project={project_id}"
            )
        return {
            "components": components,
            "targetDate": target_date,
            "isHistorical": is_historical,
            "historicalNotice": (
                f"您正在檢視歷史日期（{target_date}）之遙測資料。狀態欄依當日遙測判定，即時探測狀態僅代表當前連線狀態。"
                if is_historical
                else None
            ),
            "telemetryWindowHours": 24 if not target_date else None,
            "recentAnomalies": recent_anomalies,
            "monitoringLinks": monitoring_links,
            "simulatedAnomalies": self._settings.simulate_health_anomalies,
            "updatedAt": utc_now().isoformat(),
        }

