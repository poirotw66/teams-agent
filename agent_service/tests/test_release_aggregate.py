"""Unit tests for ReleaseAggregate domain aggregate and lifecycle invariants."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from knowledge_portal.models import ReleaseRecord
from knowledge_portal.release import (
    ACTIVE,
    DEPLOYING,
    FAILED,
    GATE_BLOCKED,
    READY,
    RELOAD_FAILED,
    ROLLED_BACK,
    ReleaseAggregate,
)


def _make_release(status: str = READY) -> ReleaseRecord:
    return ReleaseRecord(
        release_id="rel-test-001",
        created_at=datetime.now(timezone.utc),
        created_by="tester",
        status=status,
        corpus_hash="corpus-hash-123",
        index_artifact_uri="gs://bucket/index.json",
        index_setting_version="v1",
        chunk_count=10,
    )


def test_release_aggregate_properties():
    record = _make_release(READY)
    agg = ReleaseAggregate.wrap(record)
    assert agg.release_id == "rel-test-001"
    assert agg.status == READY
    assert agg.is_promotable is True
    assert agg.is_deactivatable is False
    assert agg.can_transition_to(DEPLOYING) is True
    assert agg.can_transition_to(ACTIVE) is False


def test_release_aggregate_assert_promotable():
    agg = ReleaseAggregate.wrap(_make_release(READY))
    agg.assert_promotable()  # Should not raise

    failed_agg = ReleaseAggregate.wrap(_make_release(FAILED))
    with pytest.raises(ValueError, match="cannot be promoted"):
        failed_agg.assert_promotable()


def test_release_aggregate_lifecycle_flow():
    agg = ReleaseAggregate.wrap(_make_release(READY))
    deploying = agg.mark_deploying()
    assert deploying.status == DEPLOYING

    active = deploying.mark_active()
    assert active.status == ACTIVE
    assert active.record.activated_at is not None
    assert active.is_deactivatable is True

    rolled_back = active.mark_rolled_back()
    assert rolled_back.status == ROLLED_BACK
    assert rolled_back.is_promotable is True


def test_release_aggregate_failure_and_gate_block():
    agg = ReleaseAggregate.wrap(_make_release(READY))
    blocked = agg.mark_gate_blocked(summary="Eval score below gate threshold")
    assert blocked.status == GATE_BLOCKED
    assert blocked.record.failure_summary == "Eval score below gate threshold"
    assert blocked.is_promotable is True

    failed = agg.mark_failed(summary="Build error in pipeline")
    assert failed.status == FAILED
    assert failed.record.failure_summary == "Build error in pipeline"
    assert failed.is_promotable is False


def test_release_aggregate_reload_failure():
    agg = ReleaseAggregate.wrap(_make_release(READY))
    deploying = agg.mark_deploying()
    reload_failed = deploying.mark_reload_failed(summary="Agent timeout")
    assert reload_failed.status == RELOAD_FAILED
    assert reload_failed.is_promotable is True
    assert reload_failed.is_deactivatable is True
