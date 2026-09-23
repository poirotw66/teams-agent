"""Regression: formal publish build must not starve the asyncio event loop."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from knowledge_portal.models import ReleaseRecord
from knowledge_portal.release.activation import build_deploying_candidate


class _BlockingPublisher:
    def __init__(self, block_seconds: float = 0.25) -> None:
        self.block_seconds = block_seconds
        self.calls = 0

    def build_release(self, **kwargs: Any) -> ReleaseRecord:
        self.calls += 1
        time.sleep(self.block_seconds)
        return ReleaseRecord(
            release_id=str(kwargs["release_id"]),
            status="BUILDING",
            created_at=datetime.now(timezone.utc),
            created_by=str(kwargs["created_by"]),
            previous_release_id=kwargs.get("previous_release_id"),
            corpus_hash="hash",
            index_artifact_uri="/tmp/release/index",
            index_setting_version="v1",
            chunk_count=0,
            embedding_model=kwargs.get("embedding_model") or "test",
            tenant_id=kwargs.get("tenant_id") or "default",
        )


@pytest.mark.asyncio
async def test_build_deploying_candidate_keeps_event_loop_responsive() -> None:
    publisher = _BlockingPublisher(block_seconds=0.3)
    actor = SimpleNamespace(user_id="admin", tenant_id="default")
    audit_calls: list[str] = []

    async def audit(**_kwargs: Any) -> None:
        audit_calls.append("audit")

    tick_count = 0

    async def ticker() -> None:
        nonlocal tick_count
        for _ in range(6):
            await asyncio.sleep(0.05)
            tick_count += 1

    build_task = asyncio.create_task(
        build_deploying_candidate(
            publisher=publisher,
            actor=actor,
            published_versions=[],
            release_id="rel_test",
            previous_release_id=None,
            previous_release=None,
            embedding_model="test-embed",
            correlation_id="corr",
            audit=audit,
            utc_now=lambda: datetime.now(timezone.utc),
        )
    )
    await ticker()
    release = await build_task

    assert publisher.calls == 1
    assert tick_count >= 3, "event loop should keep scheduling while build runs"
    assert release.status == "DEPLOYING"
    assert audit_calls == []
