"""Assemble component rows for the AI Ops health summary response."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from operations_core.contracts import DEFAULT_TIMEZONE, utc_now

from .query_health_telemetry import health_metric_summary
from .query_health_window import resolve_taipei_day_window


def is_historical_target(target_date: str | None) -> bool:
    if not target_date:
        return False
    try:
        _start, _end, local_target = resolve_taipei_day_window(target_date)
        local_now_date = utc_now().astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
        return local_target < local_now_date
    except Exception:
        return False


def with_scope_note(
    component_id: str,
    base: dict[str, Any],
    monitoring_scope: dict[str, Any],
) -> dict[str, Any]:
    item = dict(base)
    latency_count = int(item.get("latencySampleCount") or 0)
    request_count = int(item.get("requestCount") or 0)
    if request_count > 0 and latency_count == 0:
        existing = str(item.get("note") or "").strip()
        suffix = "有成功率樣本但無延遲樣本；P50/P95 為空不代表全鏈路延遲健康。"
        item["note"] = f"{existing} {suffix}".strip() if existing else suffix
    if component_id == "teams-adapter":
        ingress = monitoring_scope["teamsAdapter"]["ingressSampleCount"]
        if ingress and int(item.get("requestCount") or 0) == 0:
            item["note"] = (
                f"僅有入站 ADAPTER_INGRESS 樣本 ({ingress})；"
                "回覆路徑尚無 ADAPTER_REPLY，不計入 teams-adapter 可用性。"
            )
    return item


def build_raw_components(
    *,
    agent: dict[str, Any],
    agent_functional: dict[str, Any],
    adapter: dict[str, Any],
    portal: dict[str, Any],
    knowledge_release: dict[str, Any],
    ticket: dict[str, Any],
    retrieval: dict[str, Any],
    telemetry: dict[str, dict[str, Any]],
    monitoring_scope: dict[str, Any],
    ops_store_mode: str,
) -> list[dict[str, Any]]:
    no_telemetry = health_metric_summary([])
    return [
        {"id": "agent-service", **agent, **telemetry["agent-service"]},
        {"id": "agent-functional", **agent_functional, **no_telemetry},
        with_scope_note(
            "teams-adapter",
            {"id": "teams-adapter", **adapter, **telemetry["teams-adapter"]},
            monitoring_scope,
        ),
        with_scope_note(
            "agent-retrieval-index",
            {
                "id": "agent-retrieval-index",
                "status": knowledge_release.get("indexStatus")
                or agent_functional.get("status", "UNKNOWN"),
                "note": knowledge_release.get("note") or agent_functional.get("note"),
                **telemetry["agent-retrieval-index"],
            },
            monitoring_scope,
        ),
        with_scope_note(
            "agent-retrieval-search",
            {
                "id": "agent-retrieval-search",
                **retrieval,
                **telemetry["agent-retrieval-search"],
            },
            monitoring_scope,
        ),
        {"id": "llm-api", **agent, **telemetry["llm-api"]},
        {"id": "issue-extractor", **agent, **telemetry["issue-extractor"]},
        {"id": "faq-service", **agent, **telemetry["faq-service"]},
        {
            "id": "analytics-store",
            "status": "READY",
            "note": f"mode={ops_store_mode}",
            **no_telemetry,
        },
        {"id": "knowledge-portal", **portal, **no_telemetry},
        {"id": "knowledge-release", **knowledge_release, **no_telemetry},
        {"id": "ticket-service", **ticket, **telemetry["ticket-service"]},
    ]


def apply_historical_statuses(
    raw_components: list[dict[str, Any]],
    *,
    is_historical: bool,
    target_date: str | None,
) -> list[dict[str, Any]]:
    if not is_historical:
        return list(raw_components)
    components: list[dict[str, Any]] = []
    for comp in raw_components:
        live_status = str(comp.get("status") or "UNKNOWN")
        live_note = comp.get("note")
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
        components.append(
            {
                **comp,
                "status": hist_status,
                "liveProbeStatus": live_status,
                "liveProbeNote": live_note,
                "isHistorical": True,
                "note": hist_note,
            }
        )
    return components


def build_monitoring_links(project_id: str | None) -> dict[str, str]:
    if not project_id:
        return {}
    return {
        "cloudMonitoring": (
            f"https://console.cloud.google.com/monitoring/dashboards?project={project_id}"
        ),
        "cloudLogging": (
            f"https://console.cloud.google.com/logs/query;query=resource.type%3D"
            f"%22cloud_run_revision%22%0Aseverity%3E%3DERROR;"
            f"?project={project_id}"
        ),
    }
