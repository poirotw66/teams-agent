"""Release status constants and transition helpers.

Statuses mirror ``ReleaseStatus`` in ``knowledge_portal.models`` and the
values actually written by ``ReleaseService`` today. Do not invent statuses
that the runtime does not persist.
"""

from __future__ import annotations

from typing import Final

# Canonical release lifecycle statuses (see models.ReleaseStatus).
BUILDING: Final = "BUILDING"
READY: Final = "READY"
DEPLOYING: Final = "DEPLOYING"
ACTIVE: Final = "ACTIVE"
FAILED: Final = "FAILED"
GATE_BLOCKED: Final = "GATE_BLOCKED"
ROLLED_BACK: Final = "ROLLED_BACK"
RELOAD_FAILED: Final = "RELOAD_FAILED"

ALL_RELEASE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        BUILDING,
        READY,
        DEPLOYING,
        ACTIVE,
        FAILED,
        GATE_BLOCKED,
        ROLLED_BACK,
        RELOAD_FAILED,
    }
)

# Candidate releases that may enter the activate/promote path without rebuild.
PROMOTABLE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        GATE_BLOCKED,
        READY,
        RELOAD_FAILED,
        ROLLED_BACK,
    }
)

# Releases superseded when another release becomes the active pointer target.
DEACTIVATABLE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        ACTIVE,
        DEPLOYING,
        RELOAD_FAILED,
    }
)

# Observed transitions used by publish / activate / promote / rollback / sync.
# Keys are source statuses; values are allowed destinations.
ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    READY: frozenset({DEPLOYING, FAILED, GATE_BLOCKED}),
    # Fresh builds are marked DEPLOYING in memory before gate/source persistence.
    DEPLOYING: frozenset(
        {
            ACTIVE,
            FAILED,
            GATE_BLOCKED,
            RELOAD_FAILED,
            ROLLED_BACK,
        }
    ),
    ACTIVE: frozenset({ROLLED_BACK, RELOAD_FAILED}),
    GATE_BLOCKED: frozenset({DEPLOYING, GATE_BLOCKED}),
    RELOAD_FAILED: frozenset({DEPLOYING, ACTIVE, ROLLED_BACK, RELOAD_FAILED}),
    ROLLED_BACK: frozenset({DEPLOYING}),
    FAILED: frozenset(),
    BUILDING: frozenset({READY, FAILED}),
}


def is_known_status(status: str) -> bool:
    return status in ALL_RELEASE_STATUSES


def can_promote(status: str) -> bool:
    """Return True when a persisted candidate may be promoted without rebuild."""
    return status in PROMOTABLE_STATUSES


def is_deactivatable(status: str) -> bool:
    """Return True when another activation should mark this release ROLLED_BACK."""
    return status in DEACTIVATABLE_STATUSES


def can_transition(*, from_status: str, to_status: str) -> bool:
    """Validate a single status hop against observed ReleaseService behavior."""
    if from_status == to_status:
        return True
    allowed = ALLOWED_TRANSITIONS.get(from_status)
    if allowed is None:
        return False
    return to_status in allowed


def ensure_can_transition(*, from_status: str, to_status: str) -> None:
    if can_transition(from_status=from_status, to_status=to_status):
        return
    raise ValueError(
        f"Invalid release status transition: {from_status} -> {to_status}"
    )


def status_after_reload(*, reload_success: bool) -> str:
    """Terminal status after agent reload while this release owns the pointer."""
    return ACTIVE if reload_success else RELOAD_FAILED


def promote_rejection_message(*, release_id: str, status: str) -> str:
    return (
        f"Release '{release_id}' status {status} cannot be promoted; "
        "expected GATE_BLOCKED, READY, RELOAD_FAILED, or ROLLED_BACK."
    )
