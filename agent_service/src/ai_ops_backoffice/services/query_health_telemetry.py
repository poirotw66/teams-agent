"""Telemetry sample aggregation for AI Ops health summaries."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from operations_core.contracts import utc_now

from .query_health_window import resolve_taipei_day_window
from .query_math import percentile as _percentile
from .usage_projection import project_usage

UsageSample = tuple[str, str, float | None, str]
StatusLatency = tuple[str, float | None]


def health_metric_summary(
    samples: list[StatusLatency],
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
            "latencySampleCount": 0,
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
        "latencySampleCount": len(latencies),
    }


def _payload_has_timeout(payload: Any) -> bool:
    return "timeout" in json.dumps(payload).lower()


def _status_from_payload(payload: Any, *, failed: bool) -> str:
    if _payload_has_timeout(payload):
        return "TIMEOUT"
    if failed:
        return "FAILED"
    return "SUCCESS"


async def select_health_events(
    events_loader: Any,
    target_date: str | None,
) -> tuple[list[Any], datetime, datetime]:
    if target_date:
        try:
            window_start, window_end, _local_day = resolve_taipei_day_window(target_date)
            events = [
                event
                for event in await events_loader()
                if window_start <= event.occurred_at < window_end
            ]
            return events, window_start, window_end
        except Exception:
            pass
    window_end = utc_now()
    window_start = window_end - timedelta(hours=24)
    events = [event for event in await events_loader() if event.occurred_at >= window_start]
    return events, window_start, window_end


def build_failure_anomalies(failures: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "occurredAt": event.occurred_at.isoformat(),
            "component": str(event.payload.get("component") or "agent-service"),
            "status": "TIMEOUT" if _payload_has_timeout(event.payload) else "FAILED",
            "errorType": event.payload.get("errorType")
            or event.payload.get("errorCode")
            or "REQUEST_FAILED",
            "correlationId": event.correlation_id,
        }
        for event in failures
    ]


def build_request_latencies(events: list[Any]) -> dict[str, float]:
    return {
        event.request_id or event.turn_id or event.correlation_id: float(event.payload["elapsedMs"])
        for event in project_usage(events).request_latency_events
        if event.payload.get("elapsedMs") is not None
    }


def build_agent_samples(
    events: list[Any],
    failures: list[Any],
    request_latencies: dict[str, float],
) -> list[StatusLatency]:
    agent_samples: list[StatusLatency] = []
    for turn in (event for event in events if event.event_type == "turn.received"):
        failure = next(
            (
                item
                for item in failures
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
    return agent_samples


def collect_usage_samples(
    events: list[Any],
    anomalies: list[dict[str, Any]],
) -> list[UsageSample]:
    usage_samples: list[UsageSample] = []
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
                scope,
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
    return usage_samples


def filter_usage_samples(
    usage_samples: list[UsageSample],
    prefixes: tuple[str, ...],
    *,
    exclude_scopes: frozenset[str] | None = None,
    include_scopes: frozenset[str] | None = None,
) -> list[StatusLatency]:
    selected: list[StatusLatency] = []
    for component, status, latency, scope in usage_samples:
        if not component.startswith(prefixes):
            continue
        if exclude_scopes and scope in exclude_scopes:
            continue
        if include_scopes and scope not in include_scopes:
            continue
        selected.append((status, latency))
    return selected


def build_faq_and_ticket_samples(
    events: list[Any],
) -> tuple[list[StatusLatency], list[StatusLatency]]:
    faq_samples = [("SUCCESS", None) for event in events if event.event_type == "faq.answered"]
    ticket_samples = [
        (
            _status_from_payload(
                event.payload,
                failed=event.event_type == "ticket.failed",
            ),
            None,
        )
        for event in events
        if event.event_type in {"ticket.created", "ticket.failed"}
    ]
    return faq_samples, ticket_samples


def build_teams_samples(
    events: list[Any],
    usage_samples: list[UsageSample],
    request_latencies: dict[str, float],
) -> tuple[list[StatusLatency], int]:
    # Reply-path metrics only. ADAPTER_INGRESS SUCCESS without elapsedMs is
    # intentionally excluded so ingress ≠ full Teams Bot reply health.
    adapter_usage = filter_usage_samples(
        usage_samples,
        ("teams_", "adapter_", "teams-adapter", "teams_bot"),
        exclude_scopes=frozenset({"ADAPTER_INGRESS"}),
    )
    ingress_count = sum(
        1
        for component, _status, _latency, scope in usage_samples
        if component.startswith(("teams_", "adapter_", "teams-adapter", "teams_bot"))
        and scope == "ADAPTER_INGRESS"
    )
    teams_events = [
        (
            "TIMEOUT"
            if _payload_has_timeout(event.payload)
            else "FAILED"
            if str(event.payload.get("status") or "").upper() in {"FAILED", "ERROR"}
            else "SUCCESS",
            float(event.payload.get("elapsedMs"))
            if event.payload.get("elapsedMs") is not None
            else request_latencies.get(event.request_id or event.turn_id or event.correlation_id),
        )
        for event in events
        if event.event_type in {"adapter.turn_received", "teams.message_received", "teams.inbound"}
    ]
    return adapter_usage + teams_events, ingress_count


def build_index_samples(
    events: list[Any],
    usage_samples: list[UsageSample],
) -> list[StatusLatency]:
    index_samples = filter_usage_samples(
        usage_samples,
        ("knowledge_index", "indexer", "index", "retrieval_index", "embedding"),
    )
    index_events = [
        (
            "TIMEOUT"
            if _payload_has_timeout(event.payload)
            else "FAILED"
            if event.event_type.endswith(".failed")
            or str(event.payload.get("status") or "").upper() in {"FAILED", "ERROR"}
            else "SUCCESS",
            float(event.payload.get("elapsedMs"))
            if event.payload.get("elapsedMs") is not None
            else None,
        )
        for event in events
        if event.event_type in {"knowledge.indexed", "index.built", "sync.completed", "sync.failed"}
    ]
    return index_samples + index_events


def assemble_component_telemetry(
    *,
    teams_samples: list[StatusLatency],
    agent_samples: list[StatusLatency],
    usage_samples: list[UsageSample],
    faq_samples: list[StatusLatency],
    ticket_samples: list[StatusLatency],
    index_samples: list[StatusLatency],
) -> dict[str, dict[str, Any]]:
    all_usage = [
        (status, latency)
        for _component, status, latency, scope in usage_samples
        if scope not in {"ADAPTER_INGRESS", "RETRIEVAL_INDEX", "HEALTH_TELEMETRY", "ADAPTER_REPLY"}
    ]
    return {
        "teams-adapter": health_metric_summary(teams_samples),
        "agent-service": health_metric_summary(agent_samples),
        "llm-api": health_metric_summary(all_usage),
        "issue-extractor": health_metric_summary(
            filter_usage_samples(usage_samples, ("issue_extractor",))
        ),
        "faq-service": health_metric_summary(faq_samples),
        "agent-retrieval-index": health_metric_summary(index_samples),
        "agent-retrieval-search": health_metric_summary(
            filter_usage_samples(usage_samples, ("knowledge_", "gemini_file_search"))
        ),
        "ticket-service": health_metric_summary(ticket_samples),
    }


def build_monitoring_scope(
    telemetry: dict[str, dict[str, Any]],
    ingress_count: int,
) -> dict[str, Any]:
    return {
        "teamsAdapter": {
            "includes": [
                "ADAPTER_REPLY success/fail/timeout with elapsedMs",
                "legacy teams_* usage without ADAPTER_INGRESS",
            ],
            "excludes": [
                "ADAPTER_INGRESS (agent inbound SUCCESS without reply latency)",
            ],
            "ingressSampleCount": ingress_count,
            "replySampleCount": telemetry["teams-adapter"]["requestCount"],
            "latencySampleCount": telemetry["teams-adapter"]["latencySampleCount"],
            "note": (
                "Ingress SUCCESS samples are not full-chain Teams Bot health. "
                "Availability/latency use reply-path producers only."
            ),
        },
        "retrievalIndex": {
            "includes": [
                "knowledge_index sync SUCCESS/FAILED/TIMEOUT with elapsedMs",
                "RETRIEVAL_INDEX retrieval outcomes (latency optional)",
            ],
            "latencySampleCount": telemetry["agent-retrieval-index"]["latencySampleCount"],
            "note": (
                "Samples without elapsedMs still affect availability but leave P50/P95 empty."
            ),
        },
        "retrievalSearch": {
            "includes": ["knowledge_* and gemini_file_search CALL/usage samples"],
            "latencySampleCount": telemetry["agent-retrieval-search"]["latencySampleCount"],
        },
    }


async def compute_health_telemetry(
    events_loader: Any,
    target_date: str | None = None,
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    datetime,
    datetime,
    dict[str, Any],
]:
    events, window_start, window_end = await select_health_events(events_loader, target_date)
    failures = [
        event
        for event in events
        if event.event_type.endswith(".failed") or event.event_type == "request.failed"
    ]
    anomalies = build_failure_anomalies(failures)
    request_latencies = build_request_latencies(events)
    agent_samples = build_agent_samples(events, failures, request_latencies)
    usage_samples = collect_usage_samples(events, anomalies)
    faq_samples, ticket_samples = build_faq_and_ticket_samples(events)
    teams_samples, ingress_count = build_teams_samples(events, usage_samples, request_latencies)
    index_samples = build_index_samples(events, usage_samples)
    telemetry = assemble_component_telemetry(
        teams_samples=teams_samples,
        agent_samples=agent_samples,
        usage_samples=usage_samples,
        faq_samples=faq_samples,
        ticket_samples=ticket_samples,
        index_samples=index_samples,
    )
    monitoring_scope = build_monitoring_scope(telemetry, ingress_count)
    anomalies.sort(key=lambda item: item["occurredAt"], reverse=True)
    return telemetry, anomalies[:10], window_start, window_end, monitoring_scope
