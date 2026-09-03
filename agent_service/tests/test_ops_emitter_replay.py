from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_service.contracts import (
    AgentRequest,
    Citation,
    FeedbackRequest,
    Issue,
    IssueResult,
)
from agent_service.operations.classification import IssueClassifier
from agent_service.operations.emitter import (
    OperationalEventEmitter,
    OperationalEventReplayConflict,
)
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.memory_store import MemoryOperationalStore
from agent_service.operations.taxonomy import TaxonomyRepository
from agent_service.usage_events import RequestCostSummary, UsageEventCollector


def _settings() -> OpsSettings:
    data_dir = Path(__file__).resolve().parents[2] / "data" / "ops"
    return OpsSettings(
        enabled=True,
        store_mode="MEMORY",
        store_path=Path("/tmp/unused"),
        taxonomy_path=data_dir / "issue_taxonomy_v1.json",
        metrics_path=data_dir / "metrics_definitions_v1.json",
        environment="test",
        default_retention_days=365,
        transcript_retention_days=365,
        audit_retention_days=1095,
        async_emit=True,
        classification_rules_path=data_dir / "issue_classification_rules.json",
        firestore_project=None,
        firestore_database=None,
        firestore_collection="operational_events",
        bigquery_enabled=False,
        bigquery_project=None,
        bigquery_dataset="ai_ops_analytics",
        bigquery_table="operational_events",
        audit_store_mode="MEMORY",
        audit_firestore_collection="audit_events",
    )


def _emitter() -> tuple[OperationalEventEmitter, MemoryOperationalStore]:
    settings = _settings()
    store = MemoryOperationalStore()
    taxonomy = TaxonomyRepository(settings.taxonomy_path)
    return (
        OperationalEventEmitter(
            EventIngestionService(store, settings),
            taxonomy,
            IssueClassifier(taxonomy, settings.classification_rules_path),
            settings,
        ),
        store,
    )


def _request(
    *, tenant_id: str = "tenant-a", message: str = "VPN password SENSITIVE_MARKER"
) -> AgentRequest:
    return AgentRequest.model_validate(
        {
            "requestId": "request-7",
            "correlationId": "correlation-reused-by-client",
            "channel": "playground",
            "conversation": {
                "tenantId": tenant_id,
                "teamId": "team-1",
                "conversationId": "conversation-9",
            },
            "user": {"entraObjectId": "user-9"},
            "message": {"text": message, "locale": "zh-TW"},
        }
    )


def _state() -> dict[str, object]:
    return {
        "correlation_id": "correlation-reused-by-client",
        "operational_occurred_at": datetime(2026, 9, 3, 8, 0, tzinfo=UTC),
        "conversation_started": True,
        "issues": [
            Issue(
                id=1,
                description="VPN password SENSITIVE_MARKER",
                isIT=True,
                readiness="READY",
                route="KNOWLEDGE",
            ),
            Issue(
                id=2,
                description="ticket password SENSITIVE_MARKER",
                isIT=True,
                readiness="READY",
                route="TICKET",
            ),
        ],
        "issue_results": [
            IssueResult(
                issueId=1,
                resultType="KNOWLEDGE_ANSWERED",
                answer="password SENSITIVE_MARKER",
                backend="HYBRID",
                sources=[
                    Citation(
                        title="password SENSITIVE_MARKER",
                        url="https://example.test/doc?token=SENSITIVE_MARKER",
                        chunkId="chunk-1",
                    )
                ],
            ),
            IssueResult(
                issueId=2,
                resultType="FAILED",
                ticketId="ticket-7",
                error="password SENSITIVE_MARKER",
                backend="ticket-api",
            ),
        ],
        "handoff_handled": True,
    }


def test_turn_replay_has_stable_ids_timestamps_and_payloads_without_secret_leaks() -> None:
    emitter, _ = _emitter()
    first = emitter.build_turn_events(_request(), _state(), cost_summary=None)
    replay = emitter.build_turn_events(_request(), _state(), cost_summary=None)

    assert [event.model_dump(mode="json") for event in replay] == [
        event.model_dump(mode="json") for event in first
    ]
    assert len({event.event_id for event in first}) == len(first)
    assert {event.occurred_at for event in first} == {
        datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
    }
    serialized = "\n".join(event.model_dump_json() for event in first)
    assert "SENSITIVE_MARKER" not in serialized
    assert "[REDACTED_CREDENTIAL]" in serialized

    issue_events = [event for event in first if event.issue_occurrence_id]
    assert len({event.issue_occurrence_id for event in issue_events}) == 2


def test_same_request_and_conversation_in_another_tenant_does_not_collide() -> None:
    emitter, _ = _emitter()
    tenant_a = emitter.build_turn_events(_request(tenant_id="tenant-a"), _state(), cost_summary=None)
    tenant_b = emitter.build_turn_events(_request(tenant_id="tenant-b"), _state(), cost_summary=None)

    ids_a = {event.event_id for event in tenant_a}
    ids_b = {event.event_id for event in tenant_b}
    assert ids_a.isdisjoint(ids_b)
    assert next(event for event in tenant_a if event.event_type == "conversation.started").event_id != next(
        event for event in tenant_b if event.event_type == "conversation.started"
    ).event_id


def test_replay_rejects_changed_request_facts_but_allows_late_usage_phase() -> None:
    emitter, _ = _emitter()
    emitter.build_turn_events(_request(), _state(), cost_summary=None)
    with pytest.raises(OperationalEventReplayConflict, match="logical request replay"):
        emitter.build_turn_events(
            _request(message="a different request body"), _state(), cost_summary=None
        )

    collector = UsageEventCollector(
        environment="test",
        request_id="request-7",
        correlation_id="correlation-reused-by-client",
        tenant_id="tenant-a",
        team_id="team-1",
        knowledge_backend="HYBRID",
    )
    collector.record(
        component="issue_extract",
        status="SUCCESS",
        latency_ms=5.0,
        model="gpt-4o-mini",
        input_tokens=10,
        output_tokens=2,
        usage_source="PROVIDER",
    )
    late_state = _state()
    late_state["execution_context"] = SimpleNamespace(usage_collector=collector)
    summary = RequestCostSummary(
        request_id="request-7",
        correlation_id="correlation-reused-by-client",
        environment="test",
        tenant_id="tenant-a",
        team_id="team-1",
        outcome="knowledge_hit",
        knowledge_backend="HYBRID",
        elapsed_ms=10.0,
        llm_call_count=1,
        event_count=1,
        input_tokens=10,
        output_tokens=2,
        total_tokens=12,
        embedding_tokens=0,
        estimated_cost_usd=collector.events()[0].estimated_cost_usd,
        cost_complete=True,
        usage_coverage=1.0,
        pricing_version=collector.pricing_version,
    )
    late_events = emitter.build_turn_events(_request(), late_state, cost_summary=summary)
    usage_events = [event for event in late_events if event.event_type == "usage.recorded"]
    assert [event.payload["attributionScope"] for event in usage_events] == [
        "CALL",
        "REQUEST_SUMMARY",
    ]
    assert usage_events[0].payload["collectorEventId"] == collector.events()[0].event_id
    assert usage_events[0].occurred_at.isoformat() == collector.events()[0].timestamp


def test_feedback_identity_is_replay_safe_without_treating_correlation_as_unique() -> None:
    emitter, store = _emitter()
    first = FeedbackRequest(
        correlationId="corr-1",
        conversationId="conv-1",
        issueId=1,
        rating="DOWN",
        userId="user-1",
        reason="password SENSITIVE_MARKER",
        resolvedStatus="NO",
    )
    distinct = FeedbackRequest(
        correlationId="corr-1",
        conversationId="conv-1",
        issueId=2,
        rating="DOWN",
        userId="user-1",
        reason="password SENSITIVE_MARKER",
        resolvedStatus="NO",
    )

    async def run() -> None:
        await emitter.emit_feedback(first)
        await emitter.emit_feedback(first)
        await emitter.emit_feedback(distinct)

    asyncio.run(run())
    stored, _ = asyncio.run(store.list_events(limit=10))
    assert len(stored) == 2
    assert len({event.event_id for event in stored}) == 2
    assert "SENSITIVE_MARKER" not in "\n".join(event.model_dump_json() for event in stored)
