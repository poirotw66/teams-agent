from pathlib import Path

import pytest

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.faq_domain.errors import FaqTransitionError, FaqVersionConflictError
from ai_ops_backoffice.sync_domain import FileSyncRepository, SyncService

WRITER = ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ("IT",))
SYSTEM = ActorContext("system", "System", "SYSTEM_ADMIN", ())


def test_sync_job_lifecycle_retry_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "sync.json"
    service = SyncService(FileSyncRepository(path))
    created = service.create(
        scope_type="DOCUMENT",
        scope_ids=("doc-2", "doc-1"),
        owner_unit_id="IT",
        reason="rebuild selected documents",
        actor=WRITER,
        idempotency_key="sync-1",
        correlation_id="corr-1",
    )["job"]
    replay = service.create(
        scope_type="DOCUMENT",
        scope_ids=("doc-1", "doc-2"),
        owner_unit_id="IT",
        reason="rebuild selected documents",
        actor=WRITER,
        idempotency_key="sync-1",
        correlation_id="corr-1",
    )["job"]
    assert replay["job_id"] == created["job_id"]
    with pytest.raises(FaqTransitionError):
        service.create(
            scope_type="DOCUMENT",
            scope_ids=("doc-1", "doc-2"),
            owner_unit_id="IT",
            reason="duplicate active job",
            actor=WRITER,
            idempotency_key=None,
            correlation_id=None,
        )
    job_id = created["job_id"]
    validating = service.set_stage(job_id, status="VALIDATING", actor=SYSTEM)["job"]
    failed = service.set_stage(
        job_id,
        status="FAILED",
        actor=SYSTEM,
        error_summary="adapter unavailable",
    )["job"]
    assert failed["etag"] == validating["etag"] + 1
    assert failed["progress_percent"] == 20
    assert failed["checkpoint_stage"] == "VALIDATING"
    retried = service.retry(
        job_id,
        reason="adapter restored",
        actor=WRITER,
        idempotency_key="retry-1",
        correlation_id="corr-2",
    )["job"]
    assert retried["retry_of_job_id"] == job_id
    assert retried["retry_checkpoint_stage"] == "VALIDATING"
    with pytest.raises(FaqVersionConflictError):
        service.cancel(
            retried["job_id"],
            expected_etag=99,
            reason="stale",
            actor=WRITER,
        )
    cancelled = service.cancel(
        retried["job_id"],
        expected_etag=1,
        reason="operator cancelled",
        actor=WRITER,
    )["job"]
    assert cancelled["status"] == "CANCELLED"

    restarted = SyncService(FileSyncRepository(path))
    detail = restarted.detail(job_id, actor=WRITER)
    assert detail["job"]["status"] == "FAILED"
    assert [item["action"] for item in detail["audit"]] == [
        "SYNC_REQUESTED",
        "SYNC_VALIDATING",
        "SYNC_FAILED",
    ]