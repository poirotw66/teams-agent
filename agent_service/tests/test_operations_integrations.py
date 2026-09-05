from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_service.operations.audit import build_audit_event
from agent_service.operations.audit_stores import FirestoreAuditStore
from agent_service.operations.contracts import OperationalEvent, utc_now
from agent_service.operations.stores.bigquery_sink import (
    BigQueryDeliveryError,
    BigQueryEventSink,
)
from agent_service.operations.stores.firestore_store import _firestore_document
from agent_service.operations.stores.memory_store import MemoryOperationalStore
from ai_ops_backoffice.services.export_format import (
    flatten_for_csv,
    flatten_for_xlsx,
    sanitize_csv_cell,
    wrap_export_payload,
)
from ai_ops_backoffice.services.periods import resolve_period


def test_sanitize_csv_cell_blocks_formula_injection() -> None:
    assert sanitize_csv_cell("=1+1").startswith("'")
    assert sanitize_csv_cell("+123").startswith("'")
    assert sanitize_csv_cell("normal text") == "normal text"


def test_flatten_for_csv_sanitizes_values() -> None:
    csv_text = flatten_for_csv({"reason": "=HYPERLINK('evil')", "count": 3})
    assert "'=HYPERLINK('evil')" in csv_text


def test_flatten_for_xlsx_produces_zip_workbook() -> None:
    xlsx_bytes = flatten_for_xlsx({"reason": "=1+1", "count": 3})
    assert xlsx_bytes.startswith(b"PK")


def test_wrap_export_payload_includes_metadata() -> None:
    period = resolve_period(preset="7d")
    wrapped = wrap_export_payload(
        {"conversationCount": 1},
        export_type="operations_summary",
        reason="UAT",
        requested_by="owner.demo",
        requested_role="SERVICE_OWNER",
        export_format="json",
        period=period,
        pricing_version="v1",
    )
    assert wrapped["exportMetadata"]["exportType"] == "operations_summary"
    assert wrapped["exportMetadata"]["pricingVersion"] == "v1"
    assert wrapped["data"]["conversationCount"] == 1


def test_bigquery_sink_writes_schema_aligned_row() -> None:
    client = MagicMock()
    client.insert_rows_json.return_value = []
    sink = BigQueryEventSink(client, "ai_ops_analytics", "operational_events")
    event = OperationalEvent(
        event_id="evt-bq-1",
        event_type="turn.received",
        occurred_at=utc_now(),
        conversation_id="conv-1",
        correlation_id="corr-1",
        issue_type_id="vpn.connection_failed",
        payload={"messageMasked": "hello"},
    )

    async def run() -> None:
        await sink.append(event)

    asyncio.run(run())
    table_id, rows = client.insert_rows_json.call_args.args
    assert table_id == "ai_ops_analytics.operational_events"
    assert len(rows) == 1
    row = rows[0]
    expected_fields = {
        "event_id",
        "event_type",
        "schema_version",
        "occurred_at",
        "ingested_at",
        "environment",
        "tenant_id",
        "team_id",
        "channel_scope",
        "conversation_id",
        "turn_id",
        "request_id",
        "correlation_id",
        "issue_occurrence_id",
        "issue_type_id",
        "taxonomy_version",
        "actor_ref",
        "data_classification",
        "masking_policy_version",
        "retention_expires_at",
        "payload",
    }
    assert set(row.keys()) == expected_fields
    assert row["schema_version"] == 1
    assert row["environment"] == "dev"
    assert row["data_classification"] == "INTERNAL"
    assert row["retention_expires_at"] is not None
    assert row["payload"] == json.dumps({"messageMasked": "hello"}, ensure_ascii=False)
    assert "payload_json" not in row


def test_firestore_document_uses_datetime_for_ttl_field() -> None:
    expires_at = utc_now() + timedelta(days=30)
    event = OperationalEvent(
        event_id="evt-fs-1",
        event_type="turn.received",
        occurred_at=utc_now(),
        correlation_id="corr-1",
        retention_expires_at=expires_at,
        payload={"messageMasked": "hello"},
    )
    document = _firestore_document(event)
    assert isinstance(document["retention_expires_at"], type(expires_at))
    assert isinstance(document["occurred_at"], type(event.occurred_at))


def test_firestore_audit_store_writes_retention_expires_at() -> None:
    class _Snapshot:
        def __init__(self, exists: bool) -> None:
            self.exists = exists

    class _Document:
        def __init__(self) -> None:
            self.payload: dict[str, Any] | None = None

        async def get(self) -> _Snapshot:
            return _Snapshot(self.payload is not None)

        async def set(self, payload: dict[str, Any]) -> None:
            self.payload = payload

    class _Collection:
        def __init__(self) -> None:
            self.documents: dict[str, _Document] = {}

        def document(self, audit_id: str) -> _Document:
            return self.documents.setdefault(audit_id, _Document())

    class _Client:
        def __init__(self) -> None:
            self._collection = _Collection()

        def collection(self, name: str) -> _Collection:
            assert name == "audit_events"
            return self._collection

    client = _Client()
    store = FirestoreAuditStore(client, "audit_events")
    event = build_audit_event(
        actor_id="owner.demo",
        actor_role="SERVICE_OWNER",
        action="export.create",
        target_type="export_job",
        target_id="job-1",
    )

    async def run() -> None:
        await store.append(event)
        payload = client._collection.documents[event.audit_id].payload
        assert payload is not None
        assert "retention_expires_at" in payload
        assert isinstance(payload["retention_expires_at"], type(event.retention_expires_at))

    asyncio.run(run())


def test_memory_store_filters_events_by_period() -> None:
    store = MemoryOperationalStore()
    now = utc_now()
    older = now - timedelta(days=10)
    events = [
        OperationalEvent(
            event_id="evt-old",
            event_type="turn.received",
            occurred_at=older,
            correlation_id="corr-old",
            payload={},
        ),
        OperationalEvent(
            event_id="evt-new",
            event_type="turn.received",
            occurred_at=now,
            correlation_id="corr-new",
            payload={},
        ),
    ]

    async def run() -> None:
        for event in events:
            await store.append(event)
        page, cursor = await store.list_events(since=now - timedelta(days=1))
        assert [item.event_id for item in page] == ["evt-new"]
        assert cursor is None
        found = await store.find_events(correlation_id="corr-new")
        assert [item.event_id for item in found] == ["evt-new"]

    asyncio.run(run())


def test_bigquery_sink_raises_typed_error_for_rejected_rows() -> None:
    client = MagicMock()
    client.insert_rows_json.return_value = [{"errors": "schema mismatch"}]
    sink = BigQueryEventSink(client, "dataset", "table")
    event = OperationalEvent(
        event_id="evt-bq-err",
        event_type="turn.received",
        occurred_at=utc_now(),
        correlation_id="corr-1",
        payload={},
    )

    async def run() -> None:
        await sink.append(event)

    with pytest.raises(BigQueryDeliveryError, match="bigquery_row_rejected"):
        asyncio.run(run())
    client.insert_rows_json.assert_called_once()


def test_firestore_operational_store_filters_by_period() -> None:
    from fake_firestore import FakeFirestoreClient

    from agent_service.operations.stores.firestore_store import FirestoreOperationalStore

    client = FakeFirestoreClient()
    store = FirestoreOperationalStore(client, "operational_events")
    now = utc_now()
    older = now - timedelta(days=10)

    async def run() -> None:
        await store.append(
            OperationalEvent(
                event_id="evt-old",
                event_type="turn.received",
                occurred_at=older,
                correlation_id="corr-old",
                payload={},
            )
        )
        await store.append(
            OperationalEvent(
                event_id="evt-new",
                event_type="turn.received",
                occurred_at=now,
                correlation_id="corr-new",
                payload={},
            )
        )
        page, cursor = await store.list_events(since=now - timedelta(days=1))
        assert [item.event_id for item in page] == ["evt-new"]
        assert cursor is None

    asyncio.run(run())


def test_period_policy_rejects_long_custom_range() -> None:
    from ai_ops_backoffice.services.periods import PeriodPolicyError, resolve_period

    with pytest.raises(PeriodPolicyError):
        resolve_period(
            start_date="2020-01-01T00:00:00+00:00",
            end_date="2026-01-01T00:00:00+00:00",
        )
