from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.contracts import Issue
from agent_service.operations.classification import IssueClassifier
from agent_service.operations.emitter import OperationalEventEmitter
from agent_service.operations.ingestion import EventIngestionService
from agent_service.operations.settings import OpsSettings
from agent_service.operations.stores.memory_store import MemoryOperationalStore
from agent_service.operations.taxonomy import TaxonomyRepository


@pytest.fixture
def ops_paths() -> tuple[Path, Path, Path]:
    data_dir = Path(__file__).resolve().parents[2] / "data"
    return (
        data_dir / "ops" / "issue_taxonomy_v1.json",
        data_dir / "ops" / "issue_classification_rules.json",
        data_dir / "ops" / "metrics_definitions_v1.json",
    )


def test_classifier_maps_vpn_and_faq(ops_paths: tuple[Path, Path, Path]) -> None:
    taxonomy_path, rules_path, _ = ops_paths
    classifier = IssueClassifier(TaxonomyRepository(taxonomy_path), rules_path)
    vpn = classifier.classify("VPN 一直連不上", route="KNOWLEDGE")
    assert vpn.issue_type_id == "vpn.connection_failed"
    assert vpn.classification_source == "MODEL"
    faq = classifier.classify("密碼重設", route="FAQ", faq_key="PASSWORD_RESET")
    assert faq.issue_type_id == "password.reset_procedure"
    assert faq.classification_source == "FAQ_MAPPING"


def test_emitter_emits_classified_and_handoff_events(ops_paths: tuple[Path, Path, Path]) -> None:
    taxonomy_path, rules_path, metrics_path = ops_paths
    settings = OpsSettings(
        enabled=True,
        store_mode="MEMORY",
        store_path=Path("/tmp/unused"),
        taxonomy_path=taxonomy_path,
        metrics_path=metrics_path,
        environment="dev",
        default_retention_days=365,
        transcript_retention_days=365,
        audit_retention_days=1095,
        async_emit=True,
        classification_rules_path=rules_path,
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
    store = MemoryOperationalStore()
    taxonomy = TaxonomyRepository(taxonomy_path)
    classifier = IssueClassifier(taxonomy, rules_path)
    ingestion = EventIngestionService(store, settings)
    emitter = OperationalEventEmitter(ingestion, taxonomy, classifier, settings)
    issue = Issue(
        id=1,
        description="VPN 連線失敗",
        isIT=True,
        readiness="READY",
        route="KNOWLEDGE",
        missingInfo=[],
    )
    events = emitter.build_turn_events(
        _FakeRequest(),
        {
            "correlation_id": "corr-1",
            "issues": [issue],
            "issue_results": [],
            "handoff_handled": True,
            "conversation_started": True,
            "conversation": _FakeConversation(),
        },
        cost_summary=None,
    )
    types = {event.event_type for event in events}
    assert "issue.classified" in types
    assert "handoff.offered" in types
    assert "conversation.started" in types


class _FakeConversation:
    conversationId = "conv-1"
    tenantId = None
    teamId = None


class _FakeRequest:
    requestId = "req-1"
    correlationId = "corr-1"
    channel = "playground"
    conversation = _FakeConversation()
    message = type("Msg", (), {"text": "VPN 連線失敗", "locale": "zh-TW"})()
    user = type("User", (), {"entraObjectId": "user-1", "teamsUserId": None})()


def test_taxonomy_seed_has_unclassified(ops_paths: tuple[Path, Path, Path]) -> None:
    taxonomy_path, _, _ = ops_paths
    repo = TaxonomyRepository(taxonomy_path)
    active = repo.list_active()
    assert len(active) >= 20
    assert repo.get("other.unclassified") is not None


def test_event_ingestion_is_idempotent() -> None:
    from agent_service.operations.contracts import OperationalEvent, utc_now

    store = MemoryOperationalStore()
    settings = OpsSettings(
        enabled=True,
        store_mode="MEMORY",
        store_path=Path("/tmp/unused"),
        taxonomy_path=Path("/tmp/unused"),
        metrics_path=Path("/tmp/unused"),
        environment="dev",
        default_retention_days=365,
        transcript_retention_days=365,
        audit_retention_days=1095,
        async_emit=True,
        classification_rules_path=Path("/tmp/unused"),
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
    ingestion = EventIngestionService(store, settings)
    event = OperationalEvent(
        event_id="evt-1",
        event_type="turn.received",
        occurred_at=utc_now(),
        correlation_id="corr-1",
        payload={"messageMasked": "hello"},
    )

    async def run() -> None:
        assert await ingestion.ingest(event) is True
        assert await ingestion.ingest(event) is False

    import asyncio

    asyncio.run(run())


def test_masking_redacts_email_and_credentials() -> None:
    from agent_service.operations.masking import mask_text, pseudonymous_actor_id

    masked = mask_text("Contact me at user@example.test with password abc")
    assert "[REDACTED_EMAIL]" in masked.text or "[REDACTED_CREDENTIAL]" in masked.text
    assert pseudonymous_actor_id("user-123") != "user-123"


def test_composite_store_writes_primary_and_sink() -> None:
    from agent_service.operations.contracts import OperationalEvent, utc_now
    from agent_service.operations.stores.composite_store import CompositeOperationalStore
    from agent_service.operations.stores.memory_store import MemoryOperationalStore

    primary = MemoryOperationalStore()
    sink_events: list[OperationalEvent] = []

    class _Sink:
        async def append(self, event: OperationalEvent) -> bool:
            sink_events.append(event)
            return True

    store = CompositeOperationalStore(primary, [_Sink()])
    event = OperationalEvent(
        event_id="evt-composite",
        event_type="turn.received",
        occurred_at=utc_now(),
        correlation_id="corr-composite",
        payload={"messageMasked": "hello"},
    )

    async def run() -> None:
        assert await store.append(event) is True
        assert await store.append(event) is False
        page, _ = await store.list_events(limit=10)
        assert len(page) == 1

    import asyncio

    asyncio.run(run())
    assert len(sink_events) == 1
