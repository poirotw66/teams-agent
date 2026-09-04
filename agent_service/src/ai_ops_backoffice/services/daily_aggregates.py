"""Daily aggregate materialization, storage, and query helpers.

POC dashboards historically scanned period events in Python.  This module
defines the aggregate document shape, a durable file store, a materialize
worker, and a query path that can answer multi-day summaries from aggregates
when coverage is complete (falling back to event scans otherwise).
"""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from agent_service.operations.contracts import OperationalEvent, utc_now


@dataclass(frozen=True)
class DailyOpsAggregate:
    day: str
    tenant_id: str
    environment: str
    turn_count: int
    issue_count: int
    handoff_count: int
    feedback_count: int
    no_answer_count: int
    issue_type_counts: dict[str, int]
    model_token_counts: dict[str, int]
    estimated_cost_usd: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "tenantId": self.tenant_id,
            "environment": self.environment,
            "turnCount": self.turn_count,
            "issueCount": self.issue_count,
            "handoffCount": self.handoff_count,
            "feedbackCount": self.feedback_count,
            "noAnswerCount": self.no_answer_count,
            "issueTypeCounts": self.issue_type_counts,
            "modelTokenCounts": self.model_token_counts,
            "estimatedCostUsd": self.estimated_cost_usd,
            "schemaVersion": "daily-ops-aggregate-v1",
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DailyOpsAggregate:
        return cls(
            day=str(payload["day"]),
            tenant_id=str(payload.get("tenantId") or ""),
            environment=str(payload.get("environment") or ""),
            turn_count=int(payload.get("turnCount") or 0),
            issue_count=int(payload.get("issueCount") or 0),
            handoff_count=int(payload.get("handoffCount") or 0),
            feedback_count=int(payload.get("feedbackCount") or 0),
            no_answer_count=int(payload.get("noAnswerCount") or 0),
            issue_type_counts={
                str(key): int(value)
                for key, value in dict(payload.get("issueTypeCounts") or {}).items()
            },
            model_token_counts={
                str(key): int(value)
                for key, value in dict(payload.get("modelTokenCounts") or {}).items()
            },
            estimated_cost_usd=float(payload.get("estimatedCostUsd") or 0.0),
        )


def build_daily_ops_aggregates(events: list[OperationalEvent]) -> list[DailyOpsAggregate]:
    """Group in-memory events into per-day/tenant aggregates."""
    buckets: dict[tuple[str, str, str], list[OperationalEvent]] = {}
    for event in events:
        day = event.occurred_at.date().isoformat()
        tenant = event.tenant_id or ""
        key = (day, tenant, event.environment)
        buckets.setdefault(key, []).append(event)

    aggregates: list[DailyOpsAggregate] = []
    for (day, tenant, environment), group in sorted(buckets.items()):
        issue_types = Counter(
            event.issue_type_id or "other.unclassified"
            for event in group
            if event.event_type == "issue.extracted" and event.issue_type_id
        )
        model_tokens: Counter[str] = Counter()
        cost = 0.0
        for event in group:
            if event.event_type != "usage.recorded":
                continue
            model = str(event.payload.get("model") or "unknown")
            model_tokens[model] += int(event.payload.get("totalTokens") or 0)
            raw_cost = event.payload.get("estimatedCostUsd")
            if isinstance(raw_cost, (int, float)):
                cost += float(raw_cost)
        aggregates.append(
            DailyOpsAggregate(
                day=day,
                tenant_id=tenant,
                environment=environment,
                turn_count=sum(1 for event in group if event.event_type == "turn.received"),
                issue_count=sum(1 for event in group if event.event_type == "issue.extracted"),
                handoff_count=sum(
                    1 for event in group if event.event_type.startswith("handoff.")
                ),
                feedback_count=sum(
                    1 for event in group if event.event_type == "feedback.recorded"
                ),
                no_answer_count=sum(
                    1
                    for event in group
                    if event.event_type
                    in {"answer.completed", "faq.answered", "knowledge.answered"}
                    and event.payload.get("resultType") in {"NO_KNOWLEDGE", "FAILED"}
                ),
                issue_type_counts=dict(issue_types),
                model_token_counts=dict(model_tokens),
                estimated_cost_usd=round(cost, 6),
            )
        )
    return aggregates


def aggregate_document_id(*, day: str | date, tenant_id: str, environment: str) -> str:
    day_key = day.isoformat() if isinstance(day, date) else day
    tenant_key = tenant_id or "_none"
    return f"{environment}:{tenant_key}:{day_key}"


class DailyAggregateStore(Protocol):
    def upsert_many(self, aggregates: list[DailyOpsAggregate]) -> int: ...

    def list_range(
        self,
        *,
        start_day: str,
        end_day: str,
        environment: str | None = None,
        tenant_id: str | None = None,
    ) -> list[DailyOpsAggregate]: ...


class FileDailyAggregateStore:
    """JSON file store shared across Backoffice workers on one host."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for item in items:
            key = aggregate_document_id(
                day=str(item.get("day") or ""),
                tenant_id=str(item.get("tenantId") or ""),
                environment=str(item.get("environment") or ""),
            )
            result[key] = item
        return result

    def _write(self, items: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        payload = {
            "updatedAt": utc_now().isoformat(),
            "items": list(items.values()),
        }
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)

    def upsert_many(self, aggregates: list[DailyOpsAggregate]) -> int:
        with self._lock:
            items = self._read()
            for aggregate in aggregates:
                key = aggregate_document_id(
                    day=aggregate.day,
                    tenant_id=aggregate.tenant_id,
                    environment=aggregate.environment,
                )
                items[key] = aggregate.as_dict()
            self._write(items)
            return len(aggregates)

    def list_range(
        self,
        *,
        start_day: str,
        end_day: str,
        environment: str | None = None,
        tenant_id: str | None = None,
    ) -> list[DailyOpsAggregate]:
        with self._lock:
            items = self._read()
        selected: list[DailyOpsAggregate] = []
        for payload in items.values():
            day = str(payload.get("day") or "")
            if day < start_day or day > end_day:
                continue
            if environment is not None and payload.get("environment") != environment:
                continue
            if tenant_id is not None and (payload.get("tenantId") or "") != tenant_id:
                continue
            selected.append(DailyOpsAggregate.from_dict(payload))
        return sorted(selected, key=lambda item: (item.day, item.tenant_id, item.environment))


def materialize_daily_aggregates(
    events: list[OperationalEvent],
    store: DailyAggregateStore,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    environment: str | None = None,
) -> dict[str, Any]:
    """Build aggregates from events and persist them.

    When a period and environment are provided, missing calendar days are filled
    with zero rows so query coverage can complete without re-scanning events.
    """
    aggregates = build_daily_ops_aggregates(events)
    if start_at is not None and end_at is not None and environment is not None:
        scoped = [item for item in aggregates if item.environment == environment]
        tenants = {item.tenant_id for item in scoped} or {""}
        by_key = {
            (item.day, item.tenant_id, item.environment): item for item in scoped
        }
        filled: list[DailyOpsAggregate] = []
        for day in iter_day_keys(start_at=start_at, end_at=end_at):
            for tenant in tenants:
                existing = by_key.get((day, tenant, environment))
                if existing is not None:
                    filled.append(existing)
                    continue
                filled.append(
                    DailyOpsAggregate(
                        day=day,
                        tenant_id=tenant,
                        environment=environment,
                        turn_count=0,
                        issue_count=0,
                        handoff_count=0,
                        feedback_count=0,
                        no_answer_count=0,
                        issue_type_counts={},
                        model_token_counts={},
                        estimated_cost_usd=0.0,
                    )
                )
        other_env = [item for item in aggregates if item.environment != environment]
        aggregates = filled + other_env
    written = store.upsert_many(aggregates)
    return {
        "written": written,
        "days": sorted({item.day for item in aggregates}),
        "materializedAt": utc_now().isoformat(),
    }


def summarize_aggregates(aggregates: list[DailyOpsAggregate]) -> dict[str, Any]:
    """Roll daily rows into the fields operations_summary can reuse."""
    issue_types: Counter[str] = Counter()
    for item in aggregates:
        issue_types.update(item.issue_type_counts)
    return {
        "source": "daily_aggregates",
        "dayCount": len({item.day for item in aggregates}),
        "turnCount": sum(item.turn_count for item in aggregates),
        "issueOccurrenceCount": sum(item.issue_count for item in aggregates),
        "handoffCount": sum(item.handoff_count for item in aggregates),
        "feedbackCount": sum(item.feedback_count for item in aggregates),
        "noAnswerCount": sum(item.no_answer_count for item in aggregates),
        "estimatedCostUsd": round(sum(item.estimated_cost_usd for item in aggregates), 6),
        "topIssueTypes": [
            {"issueTypeId": key, "count": value}
            for key, value in issue_types.most_common(5)
        ],
    }


def iter_day_keys(*, start_at: datetime, end_at: datetime) -> list[str]:
    """Inclusive calendar days covered by [start_at, end_at)."""
    start_day = start_at.date()
    # end_at is exclusive in period helpers; last included day is the previous calendar day
    # when end is midnight, otherwise end.date().
    last = end_at.date()
    if end_at.time() == datetime.min.time() and end_at > start_at:
        last = (end_at - timedelta(microseconds=1)).date()
    days: list[str] = []
    cursor = start_day
    while cursor <= last:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def aggregates_cover_period(
    aggregates: list[DailyOpsAggregate],
    *,
    start_at: datetime,
    end_at: datetime,
    environment: str,
    explicit_range: bool = False,
) -> bool:
    """Return True when aggregate rows cover every calendar day in the period.

    Rolling windows are never treated as fully covered: whole-day rollups would
    otherwise inflate the leading partial day. Explicit custom ranges must also
    align to midnight boundaries.
    """
    if not explicit_range:
        return False
    if start_at.timetz().replace(tzinfo=None) != datetime.min.time():
        return False
    if end_at.timetz().replace(tzinfo=None) != datetime.min.time():
        return False
    needed = set(iter_day_keys(start_at=start_at, end_at=end_at))
    if not needed:
        return False
    have = {
        item.day
        for item in aggregates
        if item.environment == environment
    }
    return needed.issubset(have)


def aggregate_store_updated_at(store: Any) -> datetime | None:
    """Best-effort watermark from file-backed aggregate stores."""
    path = getattr(store, "_path", None)
    if path is None or not getattr(path, "is_file", lambda: False)():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = payload.get("updatedAt") if isinstance(payload, dict) else None
    if not raw:
        return None
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def aggregates_are_fresh(
    *,
    updated_at: datetime | None,
    max_age_minutes: int = 30,
) -> bool:
    if updated_at is None:
        return False
    age = utc_now() - updated_at
    return age.total_seconds() <= max_age_minutes * 60
