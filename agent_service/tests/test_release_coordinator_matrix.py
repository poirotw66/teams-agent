"""Release coordinator failure-matrix coverage for activate/reload branches."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from knowledge_portal.models import ReleaseRecord
from knowledge_portal.release.activation import settle_promote_after_agent_reload
from knowledge_portal.release.coordinator import (
    assert_promotable,
    compensation_target_status,
    deactivated_status,
    decide_reload_branch,
    restored_previous_status,
    should_compensate_reload_failure,
    should_finalize_as_active,
    should_mark_rolled_back,
)


@pytest.mark.parametrize(
    ("release_id", "active_id", "reload_ok", "expected"),
    [
        ("r2", "r1", True, "stale"),
        ("r2", "r2", True, "finalize"),
        ("r2", "r2", False, "compensate"),
        ("r2", None, False, "stale"),
    ],
)
def test_decide_reload_branch_matrix(
    release_id: str,
    active_id: str | None,
    reload_ok: bool,
    expected: str,
) -> None:
    assert (
        decide_reload_branch(
            release_id=release_id,
            current_active_id=active_id,
            reload_success=reload_ok,
        )
        == expected
    )


def test_compensation_and_finalize_predicates() -> None:
    assert should_compensate_reload_failure(
        release_id="r1",
        current_active_id="r1",
        reload_success=False,
    )
    assert should_finalize_as_active(
        release_id="r1",
        current_active_id="r1",
        reload_success=True,
    )
    assert not should_finalize_as_active(
        release_id="r1",
        current_active_id="r1",
        reload_success=False,
    )


def test_status_helpers_and_promote_guard() -> None:
    assert compensation_target_status() == "RELOAD_FAILED"
    assert restored_previous_status() == "ACTIVE"
    assert deactivated_status() == "ROLLED_BACK"
    assert should_mark_rolled_back("ACTIVE")
    assert_promotable(release_id="r1", status="READY")
    with pytest.raises(ValueError):
        assert_promotable(release_id="r1", status="ACTIVE")


@pytest.mark.asyncio
async def test_settle_promote_compensates_without_touching_previous_activated_at() -> None:
    now = datetime.now(timezone.utc)
    previous = ReleaseRecord(
        release_id="prev",
        status="ROLLED_BACK",
        manifest=[],
        corpus_hash="c0",
        index_artifact_uri="memory://prev",
        index_setting_version="v1",
        created_at=now,
        created_by="u1",
        activated_at=now,
    )
    candidate = ReleaseRecord(
        release_id="cand",
        status="DEPLOYING",
        manifest=[],
        corpus_hash="c1",
        index_artifact_uri="memory://cand",
        index_setting_version="v1",
        created_at=now,
        created_by="u1",
        activated_at=now,
    )
    saved: list[ReleaseRecord] = []
    reloads: list[str] = []
    pointers: list[str] = []

    class Store:
        active: str | None = "cand"

        async def get_active_release_id(self) -> str | None:
            return self.active

        async def set_active_release_id(self, release_id: str | None) -> None:
            self.active = release_id

        async def get_release(self, release_id: str) -> ReleaseRecord | None:
            if release_id == "prev":
                return previous
            return candidate

        async def save_release(self, release: object) -> None:
            assert isinstance(release, ReleaseRecord)
            saved.append(release)

        async def list_releases(self) -> list[Any]:
            return [previous, candidate]

    async def notify(release_id: str, _corr: str) -> tuple[bool, str | None]:
        reloads.append(release_id)
        return True, None

    settled = await settle_promote_after_agent_reload(
        store=Store(),
        release=candidate,
        previous_active_id="prev",
        correlation_id="corr-1",
        reload_success=False,
        reload_error="boom",
        notify_reload=notify,
        write_local_pointer=pointers.append,
        utc_now=lambda: now,
    )
    assert settled.status == "RELOAD_FAILED"
    assert settled.activated_at is None
    assert any(item.release_id == "prev" and item.status == "ACTIVE" for item in saved)
    assert all(
        item.activated_at == now for item in saved if item.release_id == "prev"
    )
    assert pointers == ["prev"]
    assert reloads == ["prev"]
