from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    assert vpn.classification_source == "KEYWORD_RULE"
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
            "operational_occurred_at": datetime(2026, 1, 2, tzinfo=UTC),
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
    turn_received = next(event for event in events if event.event_type == "turn.received")
    assert turn_received.payload.get("maskingPolicyVersion") == "v2"


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


def test_operations_phase0_scope_filter() -> None:
    from agent_service.operations.access import ActorContext
    from agent_service.operations.contracts import OperationalEvent, utc_now
    from agent_service.operations.scope import filter_events_by_scope
    from agent_service.operations.taxonomy import TaxonomyRepository

    data_dir = Path(__file__).resolve().parents[2] / "data"
    taxonomy = TaxonomyRepository(data_dir / "ops" / "issue_taxonomy_v1.json")
    actor = ActorContext(
        user_id="analyst.demo",
        display_name="Analyst",
        role="ANALYST",
        owner_unit_ids=("Other Unit",),
        tenant_id="tenant-a",
    )
    events = [
        OperationalEvent(
            event_id="evt-1",
            event_type="issue.extracted",
            occurred_at=utc_now(),
            correlation_id="corr-1",
            tenant_id="tenant-a",
            issue_type_id="vpn.connection_failed",
            payload={},
        )
    ]
    scoped = filter_events_by_scope(events, actor, taxonomy)
    assert scoped == []


def test_scope_inherits_same_turn_events_without_issue_type() -> None:
    from agent_service.operations.access import ActorContext
    from agent_service.operations.contracts import OperationalEvent, utc_now
    from agent_service.operations.scope import filter_events_by_scope
    from agent_service.operations.taxonomy import TaxonomyRepository

    data_dir = Path(__file__).resolve().parents[2] / "data"
    taxonomy = TaxonomyRepository(data_dir / "ops" / "issue_taxonomy_v1.json")
    actor = ActorContext(
        user_id="analyst.demo",
        display_name="Analyst",
        role="ANALYST",
        owner_unit_ids=("IT Service Desk",),
        tenant_id="tenant-a",
    )
    now = utc_now()
    events = [
        OperationalEvent(
            event_id="issue-1",
            event_type="issue.extracted",
            occurred_at=now,
            conversation_id="conv-1",
            turn_id="turn-1",
            tenant_id="tenant-a",
            correlation_id="corr-1",
            issue_type_id="vpn.connection_failed",
            payload={},
        ),
        OperationalEvent(
            event_id="turn-1",
            event_type="turn.received",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-1",
            turn_id="turn-1",
            tenant_id="tenant-a",
            payload={"messageMasked": "hello"},
        ),
        OperationalEvent(
            event_id="turn-orphan",
            event_type="turn.received",
            occurred_at=now,
            conversation_id="conv-1",
            correlation_id="corr-2",
            turn_id="turn-2",
            tenant_id="tenant-a",
            payload={"messageMasked": "secret"},
        ),
    ]
    scoped = filter_events_by_scope(events, actor, taxonomy)
    scoped_ids = {event.event_id for event in scoped}
    assert "turn-1" in scoped_ids
    assert "issue-1" in scoped_ids
    assert "turn-orphan" not in scoped_ids


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


def test_purge_expired_events_removes_only_expired_records() -> None:
    from agent_service.operations.contracts import OperationalEvent, utc_now
    from agent_service.operations.retention import purge_expired_events
    from agent_service.operations.stores.memory_store import MemoryOperationalStore

    now = utc_now()
    events = [
        OperationalEvent(
            event_id="active",
            event_type="turn.received",
            occurred_at=now,
            correlation_id="corr-active",
            retention_expires_at=now + timedelta(days=1),
            payload={"messageMasked": "active"},
        ),
        OperationalEvent(
            event_id="expired",
            event_type="turn.received",
            occurred_at=now,
            correlation_id="corr-expired",
            retention_expires_at=now - timedelta(seconds=1),
            payload={"messageMasked": "expired"},
        ),
    ]

    kept, removed = purge_expired_events(events)
    assert removed == 1
    assert [event.event_id for event in kept] == ["active"]

    async def run_store_purge() -> int:
        store = MemoryOperationalStore()
        for event in events:
            await store.append(event)
        return await store.purge_expired()

    import asyncio

    assert asyncio.run(run_store_purge()) == 1


def test_phase0_deliverable_artifacts_exist(ops_paths: tuple[Path, Path, Path]) -> None:
    """Phase 0 §15: required data dictionary and governance artifacts are present."""
    data_dir = ops_paths[0].parent
    required = [
        "operational_event_schema_v1.json",
        "role_capability_matrix_v1.json",
        "data_governance_decisions_v1.json",
    ]
    for name in required:
        assert (data_dir / name).is_file(), f"missing deliverable: {name}"


def test_role_capability_matrix_matches_code() -> None:
    import json

    from agent_service.operations.access import CAPABILITIES

    data_dir = Path(__file__).resolve().parents[2] / "data" / "ops"
    matrix = json.loads((data_dir / "role_capability_matrix_v1.json").read_text(encoding="utf-8"))
    for role_entry in matrix["roles"]:
        role = role_entry["role"]
        expected = set(CAPABILITIES[role])
        actual = set(role_entry["capabilities"])
        assert actual == expected, f"matrix drift for role {role}"


def test_system_admin_is_highest_privilege_role() -> None:
    from agent_service.operations.access import CAPABILITIES

    admin_capabilities = CAPABILITIES["SYSTEM_ADMIN"]
    for role, capabilities in CAPABILITIES.items():
        assert admin_capabilities.issuperset(capabilities), f"SYSTEM_ADMIN missing {role} capability"


def test_signoff_checklist_sync_preserves_approvals(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "ops_signoff_checklist.py"
    checklist_path = tmp_path / "ai_ops_signoff_checklist.json"

    subprocess.run(
        [sys.executable, str(script), "--write", str(checklist_path)],
        cwd=repo_root,
        check=True,
    )
    payload = json.loads(checklist_path.read_text(encoding="utf-8"))
    payload["signOffItems"][0]["status"] = "approved"
    payload["signOffItems"][0]["approvedBy"] = "bu.reviewer"
    payload["signOffItems"][0]["approvedAt"] = "2026-09-02T00:00:00+00:00"
    checklist_path.write_text(json.dumps(payload), encoding="utf-8")

    subprocess.run(
        [sys.executable, str(script), "--sync", str(checklist_path)],
        cwd=repo_root,
        check=True,
    )
    synced = json.loads(checklist_path.read_text(encoding="utf-8"))
    first_item = synced["signOffItems"][0]
    assert first_item["status"] == "approved"
    assert first_item["approvedBy"] == "bu.reviewer"
    assert first_item["approvedAt"] == "2026-09-02T00:00:00+00:00"
    assert "reviewArtifacts" in first_item


def test_signoff_approve_records_approval(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts/ops_signoff_checklist.py"
    approve_script = repo_root / "scripts/ops_signoff_approve.py"
    checklist_path = tmp_path / "ai_ops_signoff_checklist.json"

    subprocess.run(
        [sys.executable, str(script), "--write", str(checklist_path)],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(approve_script),
            "--checklist",
            str(checklist_path),
            "--item",
            "it-terraform",
            "--by",
            "it.reviewer",
            "--at",
            "2026-09-02T01:00:00+00:00",
            "--notes",
            "Zero-diff plan verified.",
        ],
        cwd=repo_root,
        check=True,
    )
    payload = json.loads(checklist_path.read_text(encoding="utf-8"))
    item = next(entry for entry in payload["signOffItems"] if entry["id"] == "it-terraform")
    assert item["status"] == "approved"
    assert item["approvedBy"] == "it.reviewer"
    assert item["notes"] == "Zero-diff plan verified."
