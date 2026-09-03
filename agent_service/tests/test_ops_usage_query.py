from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import OperationalEvent, utc_now
from ai_ops_backoffice.services.query_service import BackofficeQueryService
from ai_ops_backoffice.services.reconciliation import (
    reconcile_costs_summary,
    reconcile_operations_summary,
)
from ai_ops_backoffice.services.usage_projection import project_usage

ACTOR = ActorContext(
    user_id="test", display_name="Test", role="ANALYST", owner_unit_ids=()
)


def _event(key: str, payload: dict, *, tenant: str = "tenant", request: str = "req"):
    return OperationalEvent(
        event_id=key, event_type="usage.recorded", occurred_at=utc_now(),
        environment="test", tenant_id=tenant, conversation_id="conv",
        request_id=request, turn_id=request, correlation_id="shared-correlation",
        payload=payload,
    )


def _call(key="call", *, cost=0.1, model="model-a", **kwargs):
    return _event(key, {
        "attributionScope": "CALL", "collectorEventId": key,
        "model": model, "provider": "provider-" + model, "component": "generate",
        "inputTokens": 10, "toolContextTokens": 3, "embeddingTokens": 2,
        "outputTokens": 5, "totalTokens": 20, "llmCallCount": 1,
        "estimatedCostUsd": cost, "costComplete": cost is not None,
        "usageSource": "PROVIDER", "usageComplete": True,
        "pricingVersion": "price-" + model, "elapsedMs": 5,
    }, **kwargs)


def _summary(key="summary", *, cost=0.3, elapsed=1200, calls=2, tokens=40, **kwargs):
    return _event(key, {
        "attributionScope": "REQUEST_SUMMARY",
        "summary": {
            "estimatedCostUsd": cost, "costComplete": cost is not None or calls == 0,
            "usageComplete": True, "usageCoverage": 1.0,
            "elapsedMs": elapsed, "totalTokens": tokens, "llmCallCount": calls,
            "inputTokens": tokens * 3 // 4, "outputTokens": tokens // 4,
            "pricingVersion": "request-price",
        },
    }, **kwargs)


def _query(events):
    query = object.__new__(BackofficeQueryService)
    query._metrics = {}
    query._runtime = SimpleNamespace(taxonomy=SimpleNamespace(get=lambda _: None))
    # Exercise actual query aggregators, using an already-scoped input boundary.
    query._scoped_events = AsyncMock(return_value=events)
    return query


@pytest.mark.asyncio
async def test_call_cost_dimensions_and_request_metrics_do_not_double_count():
    a, b = _call(), _call("call-b", cost=0.2, model="model-b")
    query = _query([a, b, _summary(), a])
    costs = await query.costs_summary(ACTOR)
    ops = await query.operations_summary(ACTOR)
    assert costs["totalEstimatedCostUsd"] == ops["estimatedCostUsd"] == 0.3
    assert costs["eventCount"] == costs["llmCallCount"] == 2
    assert costs["inputTokens"] == 20
    assert costs["toolContextTokens"] == 6
    assert costs["embeddingTokens"] == 4
    assert ops["totalTokens"] == 40
    assert ops["costCoverage"] == 1.0
    assert ops["p95LatencyMs"] == 1200
    assert [(m["model"], m["estimatedCostUsd"]) for m in costs["byModel"]] == [
        ("model-a", 0.1), ("model-b", 0.2),
    ]
    assert {p["pricingVersion"] for p in costs["pricingVersionsObserved"]} == {
        "price-model-a", "price-model-b",
    }
    assert (await reconcile_costs_summary(query, ACTOR))["allMatch"]


@pytest.mark.asyncio
async def test_summary_only_legacy_and_call_only_fallbacks():
    legacy = _event("legacy", {
        "estimatedCostUsd": 0.4, "totalTokens": 50, "elapsedMs": 500,
    }, request="legacy")
    query = _query([
        _summary(cost=0.8, calls=1, tokens=20),
        _call("only-call", cost=0.2, request="call-only"), legacy,
    ])
    costs = await query.costs_summary(ACTOR)
    ops = await query.operations_summary(ACTOR)
    assert costs["totalEstimatedCostUsd"] == ops["estimatedCostUsd"] == 1.4
    assert costs["eventCount"] == 3
    assert ops["costCoverage"] == 1.0
    assert len(project_usage(query._scoped_events.return_value).request_latency_events) == 2
    assert (await reconcile_operations_summary(query, ACTOR))["allMatch"]
    assert (await reconcile_costs_summary(query, ACTOR))["allMatch"]


@pytest.mark.asyncio
async def test_unknown_price_and_zero_calls_are_distinct():
    query = _query([_call(cost=None), _summary(cost=None, calls=1, tokens=20)])
    costs = await query.costs_summary(ACTOR)
    ops = await query.operations_summary(ACTOR)
    assert costs["totalEstimatedCostUsd"] is None
    assert costs["totalEstimatedCostTwd"] is None
    assert costs["byModel"][0]["estimatedCostUsd"] is None
    assert costs["missingCostEventCount"] == 1
    assert ops["costCoverage"] == 0
    assert ops["estimatedCostUsd"] is None
    assert (await reconcile_costs_summary(query, ACTOR))["allMatch"]

    query = _query([_summary(cost=None, calls=0, tokens=0)])
    assert (await query.costs_summary(ACTOR))["missingCostEventCount"] == 0
    assert (await query.operations_summary(ACTOR))["costCoverage"] == 1


@pytest.mark.asyncio
async def test_request_p95_and_tenant_separation_with_reused_identifiers():
    events = []
    for index in range(20):
        kwargs = {"tenant": str(index)}
        events.extend([
            _call(**kwargs), _summary(cost=0.1, calls=1, tokens=20,
                                      elapsed=(index + 1) * 1000, **kwargs),
        ])
    query = _query(events)
    assert (await query.operations_summary(ACTOR))["p95LatencyMs"] == 19000
    assert (await query.costs_summary(ACTOR))["totalEstimatedCostUsd"] == 2.0
    assert len(project_usage(events).request_events) == 20


@pytest.mark.asyncio
async def test_multiple_issues_do_not_receive_arbitrary_request_cost():
    call = _call()
    issues = [
        call.model_copy(update={
            "event_id": f"issue-{i}", "event_type": "issue.extracted",
            "issue_type_id": f"type-{i}", "issue_occurrence_id": f"occurrence-{i}",
            "payload": {},
        })
        for i in (1, 2)
    ]
    query = _query([*issues, call, _summary(cost=0.1, calls=1, tokens=20)])
    costs = await query.costs_summary(ACTOR)
    assert costs["byIssueType"] == [
        {"issueTypeId": "unknown", "displayName": "unknown", "estimatedCostUsd": 0.1}
    ]
    assert (await reconcile_costs_summary(query, ACTOR))["allMatch"]


def test_projection_rejects_conflicting_duplicate_usage():
    call = _call()
    with pytest.raises(ValueError, match="conflicting usage event"):
        project_usage([call, call.model_copy(update={"payload": {"estimatedCostUsd": 999}})])
