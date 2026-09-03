"""Canonical views over legacy and Phase-0 usage event shapes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_service.operations.contracts import OperationalEvent


def usage_scope(event: OperationalEvent) -> str:
    value = event.payload.get("attributionScope")
    return str(value) if value else "LEGACY"


def request_key(event: OperationalEvent) -> tuple[str, ...]:
    scope = (event.environment, event.tenant_id or "", event.conversation_id or "")
    if event.request_id:
        return (*scope, "request", event.request_id)
    if event.turn_id:
        return (*scope, "turn", event.turn_id)
    return (*scope, "correlation", event.correlation_id)


def _summary_event(event: OperationalEvent) -> OperationalEvent:
    summary = event.payload.get("summary")
    if not isinstance(summary, dict):
        raise TypeError("REQUEST_SUMMARY usage event requires an object summary")
    return event.model_copy(update={
        "payload": {
            **summary, "costComplete": _cost_complete(summary),
            "attributionScope": "REQUEST_SUMMARY",
        }
    })


def _cost_complete(payload: dict[str, Any]) -> bool:
    zero_call = (
        payload.get("llmCallCount") == 0 and payload.get("totalTokens") == 0
        and payload.get("costComplete") is True
    )
    return (
        payload.get("costComplete") is not False
        and payload.get("usageComplete") is not False
        and payload.get("usageSource") != "MISSING"
        and float(payload.get("usageCoverage", 1.0)) == 1.0
        and (payload.get("estimatedCostUsd") is not None or zero_call)
    )


def _aggregate_calls(calls: list[OperationalEvent]) -> OperationalEvent:
    first = min(calls, key=lambda event: event.occurred_at)
    costs = [event.payload.get("estimatedCostUsd") for event in calls]
    known_cost = sum(float(value) for value in costs if value is not None)
    complete = all(_cost_complete(event.payload) for event in calls)
    return first.model_copy(update={
        "payload": {
            "totalTokens": sum(int(event.payload.get("totalTokens") or 0) for event in calls),
            "inputTokens": sum(int(event.payload.get("inputTokens") or 0) for event in calls),
            "outputTokens": sum(int(event.payload.get("outputTokens") or 0) for event in calls),
            "embeddingTokens": sum(
                int(event.payload.get("embeddingTokens") or 0) for event in calls
            ),
            "toolContextTokens": sum(
                int(event.payload.get("toolContextTokens") or 0) for event in calls
            ),
            "estimatedCostUsd": known_cost if any(value is not None for value in costs) else None,
            "costComplete": complete,
            "usageComplete": all(
                event.payload.get("usageComplete", True) is True for event in calls
            ),
            "llmCallCount": sum(
                int(event.payload.get("llmCallCount") or 0) for event in calls
            ),
        }
    })


@dataclass(frozen=True)
class UsageProjection:
    detail_events: tuple[OperationalEvent, ...]
    request_events: tuple[OperationalEvent, ...]
    request_latency_events: tuple[OperationalEvent, ...]


def project_usage(events: list[OperationalEvent]) -> UsageProjection:
    usage = [event for event in events if event.event_type == "usage.recorded"]
    # Firestore is idempotent by event ID; file/replay input still gets strict
    # conflict detection before analytics.
    by_identity: dict[tuple[str, str | None, str], OperationalEvent] = {}
    for event in usage:
        identity = (event.environment, event.tenant_id, event.event_id)
        known = by_identity.get(identity)
        if known and known.model_dump(mode="json") != event.model_dump(mode="json"):
            raise ValueError(f"conflicting usage event identity: {event.event_id}")
        by_identity[identity] = event
    usage = list(by_identity.values())
    groups: dict[tuple[str, ...], list[OperationalEvent]] = {}
    for event in usage:
        groups.setdefault(request_key(event), []).append(event)

    detail: list[OperationalEvent] = []
    requests: list[OperationalEvent] = []
    latencies: list[OperationalEvent] = []
    for group in groups.values():
        calls = [event for event in group if usage_scope(event) == "CALL"]
        summaries = [event for event in group if usage_scope(event) == "REQUEST_SUMMARY"]
        legacy = [event for event in group if usage_scope(event) == "LEGACY"]
        unknown = [
            event for event in group if usage_scope(event) not in {"CALL", "REQUEST_SUMMARY", "LEGACY"}
        ]
        if unknown:
            raise ValueError("unknown usage attributionScope")
        if len(summaries) > 1:
            raise ValueError("multiple request usage summaries for one logical request")
        if calls:
            detail.extend(calls)
        elif summaries:
            # Summary-only is an explicit request fallback. Its model/provider
            # dimensions remain unknown; no first-model allocation is made.
            detail.append(_summary_event(summaries[0]))
        else:
            detail.extend(legacy)
        if summaries:
            summary = _summary_event(summaries[0])
            requests.append(summary)
            if summary.payload.get("elapsedMs") is not None:
                latencies.append(summary)
        elif calls:
            requests.append(_aggregate_calls(calls))
        else:
            requests.extend(event.model_copy(update={
                "payload": {**event.payload, "costComplete": _cost_complete(event.payload)}
            }) for event in legacy)
            latencies.extend(
                event for event in legacy if event.payload.get("elapsedMs") is not None
            )
    return UsageProjection(tuple(detail), tuple(requests), tuple(latencies))


def confirmed_zero_call(event: OperationalEvent) -> bool:
    payload = event.payload
    return (
        payload.get("costComplete") is True
        and payload.get("llmCallCount") == 0
        and payload.get("totalTokens") == 0
    )


def known_cost_total(events: list[OperationalEvent] | tuple[OperationalEvent, ...]) -> float | None:
    values = [e.payload["estimatedCostUsd"] for e in events if e.payload.get("estimatedCostUsd") is not None]
    if values:
        return round(sum(float(value) for value in values), 6)
    return 0.0 if all(confirmed_zero_call(event) for event in events) else None


def usage_breakdown(events: list[OperationalEvent], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[OperationalEvent]] = {}
    for event in events:
        groups.setdefault(str(event.payload.get(field) or "unknown"), []).append(event)
    return [
        {
            field: name, "eventCount": len(group), "estimatedCostUsd": known_cost_total(group),
            "costCoverage": round(sum(_cost_complete(e.payload) for e in group) / len(group), 4),
            **{
                key: sum(int(event.payload.get(key) or 0) for event in group)
                for key in (
                    "inputTokens", "outputTokens", "toolContextTokens", "embeddingTokens", "llmCallCount"
                )
            },
        }
        for name, group in sorted(groups.items())
    ]


class UsageDimensions:
    """Resolve only explicit occurrence links; legacy joins require uniqueness."""

    def __init__(self, events: list[OperationalEvent]) -> None:
        self._issues: dict[tuple[object, ...], set[str]] = {}
        self._routes: dict[tuple[object, ...], set[str]] = {}
        for event in events:
            scope = (event.environment, event.tenant_id, event.conversation_id)
            keys = [(*scope, "correlation", event.correlation_id)]
            if event.issue_occurrence_id:
                keys.append((*scope, "occurrence", event.issue_occurrence_id))
            for key in keys:
                if event.event_type in {"issue.extracted", "issue.classified"} and event.issue_type_id:
                    self._issues.setdefault(key, set()).add(event.issue_type_id)
                if event.event_type == "route.selected" and event.payload.get("route"):
                    self._routes.setdefault(key, set()).add(str(event.payload["route"]))

    def resolve(self, event: OperationalEvent) -> tuple[str, str]:
        scope = (event.environment, event.tenant_id, event.conversation_id)
        if event.issue_occurrence_id:
            key = (*scope, "occurrence", event.issue_occurrence_id)
        elif usage_scope(event) == "LEGACY":
            key = (*scope, "correlation", event.correlation_id)
        else:
            return str(event.payload.get("route") or "unknown"), event.issue_type_id or "unknown"
        issues = self._issues.get(key, set())
        routes = self._routes.get(key, set())
        issue = event.issue_type_id or (next(iter(issues)) if len(issues) == 1 else "unknown")
        route = next(iter(routes)) if len(routes) == 1 else "unknown"
        return route, issue
