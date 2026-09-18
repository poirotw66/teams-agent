"""Pure coordination helpers for release status and compensation decisions.

These extract clearly separable logic from ``ReleaseService`` without owning
the activation saga (build, gate, source persistence, pointer, reload).
"""

from __future__ import annotations

from typing import Literal

from .transitions import (
    ACTIVE,
    RELOAD_FAILED,
    ROLLED_BACK,
    can_promote,
    can_transition,
    ensure_can_transition,
    is_deactivatable,
    promote_rejection_message,
    status_after_reload,
)

ReloadBranch = Literal["compensate", "finalize", "stale"]


def assert_promotable(*, release_id: str, status: str) -> None:
    """Raise ``ValueError`` when a candidate cannot enter the promote path.

    ``ReleaseService.promote_candidate_release`` translates this into
    ``PortalPermissionError`` to preserve the existing API error type.
    """
    if can_promote(status):
        return
    raise ValueError(promote_rejection_message(release_id=release_id, status=status))


def should_mark_rolled_back(status: str) -> bool:
    """Whether ``_deactivate_other_releases`` should rewrite this status."""
    return is_deactivatable(status)


def decide_reload_branch(
    *,
    release_id: str,
    current_active_id: str | None,
    reload_success: bool,
) -> ReloadBranch:
    """Classify post-reload handling while preserving ReleaseService branching."""
    if current_active_id != release_id:
        return "stale"
    if reload_success:
        return "finalize"
    return "compensate"


def should_compensate_reload_failure(
    *,
    release_id: str,
    current_active_id: str | None,
    reload_success: bool,
) -> bool:
    """True when activate/promote owns the pointer but agent reload failed."""
    return (
        decide_reload_branch(
            release_id=release_id,
            current_active_id=current_active_id,
            reload_success=reload_success,
        )
        == "compensate"
    )


def should_finalize_as_active(
    *,
    release_id: str,
    current_active_id: str | None,
    reload_success: bool,
) -> bool:
    """True when activate should persist ACTIVE after a successful reload."""
    return (
        decide_reload_branch(
            release_id=release_id,
            current_active_id=current_active_id,
            reload_success=reload_success,
        )
        == "finalize"
    )


def compensation_target_status() -> str:
    """Status written on the failed candidate during reload compensation."""
    return RELOAD_FAILED


def restored_previous_status() -> str:
    """Status restored on the previous release after reload compensation."""
    return ACTIVE


def deactivated_status() -> str:
    """Status written when another release supersedes this one."""
    return ROLLED_BACK


def resolve_post_reload_status(*, reload_success: bool) -> str:
    """Map reload outcome to ACTIVE or RELOAD_FAILED."""
    return status_after_reload(reload_success=reload_success)


def validate_status_hop(*, from_status: str, to_status: str) -> None:
    """Raise when a hop is outside the observed release state machine."""
    ensure_can_transition(from_status=from_status, to_status=to_status)


def is_allowed_status_hop(*, from_status: str, to_status: str) -> bool:
    return can_transition(from_status=from_status, to_status=to_status)


__all__ = [
    "ReloadBranch",
    "assert_promotable",
    "compensation_target_status",
    "deactivated_status",
    "decide_reload_branch",
    "is_allowed_status_hop",
    "resolve_post_reload_status",
    "restored_previous_status",
    "should_compensate_reload_failure",
    "should_finalize_as_active",
    "should_mark_rolled_back",
    "validate_status_hop",
]
