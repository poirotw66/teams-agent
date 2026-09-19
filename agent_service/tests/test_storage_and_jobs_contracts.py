"""Tests for Milestone 5: Data Storage & Async Job Contract Governance.

Validates:
- Firestore schema contracts: OutboxRecord (operational_delivery_outbox), QualityState, SyncState
- Schema versioning and backward compatibility for stored entity states
- Typed background job payloads for ExportJob, SyncJob, and Cloud Tasks
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai_ops_backoffice.quality_domain.models import QualityState
from ai_ops_backoffice.services.export_models import (
    ExportJob,
    deserialize_export_job,
    serialize_export_job,
    validate_export_request_params,
)
from ai_ops_backoffice.services.job_payload_contracts import (
    IngestionTaskPayload,
    SyncTaskPayload,
)
from ai_ops_backoffice.sync_domain.models import SyncJob, SyncState
from operations_core.contracts import OperationalEvent
from operations_core.outbox_contracts import (
    OUTBOX_SCHEMA_VERSION,
    DeliveryTargetState,
    OutboxRecord,
)


def test_outbox_record_contract_and_firestore_serialization() -> None:
    now = datetime.now(UTC)
    event = OperationalEvent(
        event_id="evt-100",
        event_type="conversation.started",
        occurred_at=now,
        correlation_id="corr-100",
    )

    record = OutboxRecord(
        fingerprint="fp-test-123",
        event=event,
        created_at=1000.0,
        expires_at=2000.0,
        deliveries={
            "__primary__": DeliveryTargetState(status="pending", attempts=1),
            "bigquery": DeliveryTargetState(status="leased", token="tok-1", attempts=2),
        },
        wake_at=1500.0,
    )

    firestore_dict = record.to_firestore_dict()
    assert firestore_dict["schema_version"] == OUTBOX_SCHEMA_VERSION
    assert firestore_dict["fingerprint"] == "fp-test-123"
    assert firestore_dict["deliveries"]["bigquery"]["status"] == "leased"
    assert firestore_dict["deliveries"]["bigquery"]["token"] == "tok-1"

    # Test backward compatibility deserialization
    hydrated = OutboxRecord.from_firestore_dict(firestore_dict)
    assert hydrated.schema_version == OUTBOX_SCHEMA_VERSION
    assert hydrated.event is not None
    assert hydrated.event.event_id == "evt-100"
    assert hydrated.deliveries["__primary__"].status == "pending"
    assert hydrated.deliveries["__primary__"].attempts == 1


def test_outbox_record_backward_compatibility_with_legacy_payload() -> None:
    # Simulate a legacy Firestore document with no schema_version and extra unmodeled fields
    legacy_doc = {
        "fingerprint": "fp-legacy-999",
        "created_at": 500.0,
        "expires_at": 1000.0,
        "wake_at": 600.0,
        "unknown_legacy_metadata": "should_be_ignored",
        "deliveries": {
            "__primary__": {
                "status": "done",
                "attempts": 1,
                "legacy_internal_flag": True,
            }
        },
    }

    record = OutboxRecord.from_firestore_dict(legacy_doc)
    assert record.schema_version == OUTBOX_SCHEMA_VERSION
    assert record.fingerprint == "fp-legacy-999"
    assert record.event is None
    assert record.deliveries["__primary__"].status == "done"
    assert record.deliveries["__primary__"].attempts == 1


def test_export_request_params_validation_and_contracts() -> None:
    raw_params = {
        "actor_ref": "user@example.com",
        "issue_type_id": "account.login",
        "query": "login failure",
        "unknown_extra_param": "ignored_value",
    }
    validated = validate_export_request_params("conversations", raw_params)
    assert validated["actor_ref"] == "user@example.com"
    assert validated["issue_type_id"] == "account.login"
    assert validated["query"] == "login failure"
    assert "unknown_extra_param" not in validated

    feedback_params = {
        "rating": 1,
        "feedback_reason": "incorrect answer",
        "handoff": True,
    }
    validated_feedback = validate_export_request_params("feedback", feedback_params)
    assert validated_feedback["rating"] == 1
    assert validated_feedback["feedback_reason"] == "incorrect answer"
    assert validated_feedback["handoff"] is True


def test_export_job_schema_version_and_deserialization() -> None:
    job = ExportJob(
        job_id="job-1",
        export_type="conversations",
        export_format="json",
        status="QUEUED",
        reason="compliance",
        requested_by="admin-user",
        requested_role="admin",
        days=7,
        created_at="2026-09-19T00:00:00Z",
        expires_at="2026-09-26T00:00:00Z",
    )
    assert job.schema_version == 1

    payload = serialize_export_job(job)
    assert payload["schema_version"] == 1

    # Simulate legacy deserialization without schema_version field
    payload.pop("schema_version")
    deserialized = deserialize_export_job(payload)
    assert deserialized.schema_version == 1
    assert deserialized.job_id == "job-1"


def test_sync_job_and_state_schema_version() -> None:
    now = datetime.now(UTC)
    job = SyncJob(
        job_id="sync-001",
        scope_type="ALL",
        scope_key="all-docs",
        requested_by="ops-engineer",
        owner_unit_id="ops",
        reason="nightly sync",
        correlation_id="corr-sync-1",
        requested_at=now,
    )
    assert job.schema_version == 1

    state = SyncState(revision=1, jobs=(job,))
    assert state.schema_version == 1
    assert len(state.jobs) == 1
    assert state.jobs[0].job_id == "sync-001"


def test_quality_state_schema_version() -> None:
    state = QualityState(revision=3)
    assert state.schema_version == 1
    assert state.revision == 3


def test_cloud_tasks_payload_contracts() -> None:
    sync_task = SyncTaskPayload(
        job_id="sync-job-99",
        action="sync",
        scope_type="FAQ",
        scope_ids=("faq-1", "faq-2"),
        correlation_id="corr-sync-99",
    )
    assert sync_task.schema_version == 1
    assert sync_task.scope_ids == ("faq-1", "faq-2")

    ingestion_task = IngestionTaskPayload(
        job_id="pdf-job-88",
        action="run",
        tenant_id="tenant-alpha",
    )
    assert ingestion_task.schema_version == 1
    assert ingestion_task.tenant_id == "tenant-alpha"
