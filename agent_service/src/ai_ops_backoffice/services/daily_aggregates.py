"""Daily aggregate scaffolding for analytics growth path.

POC query paths still scan period events in Python.  These helpers define the
stable aggregate document shape so a later worker can materialize
``daily/{date}`` rows without changing dashboard contracts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

from agent_service.operations.contracts import OperationalEvent


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
                    if event.event_type in {"answer.completed", "faq.answered", "knowledge.answered"}
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
