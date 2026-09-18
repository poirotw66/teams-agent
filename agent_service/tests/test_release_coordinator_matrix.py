"""Release coordinator failure-matrix coverage for activate/reload branches."""

from __future__ import annotations

import pytest

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
