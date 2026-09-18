"""Activation saga steps that compose release ports.

Extracted from ``ReleaseService._activate_release`` so the service owns
publisher/build orchestration while reload settlement lives here.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar

from knowledge_portal.models import ReleaseRecord

from .coordinator import (
    compensation_target_status,
    decide_reload_branch,
    restored_previous_status,
)
from .ports import ActivationStorePort
from .transitions import FAILED, GATE_BLOCKED

logger = logging.getLogger(__name__)

ReleaseT = TypeVar("ReleaseT", bound=ReleaseRecord)
NotifyReload = Callable[[str, str], Awaitable[tuple[bool, str | None]]]
WriteLocalPointer = Callable[[str], None]
UtcNow = Callable[[], datetime]


def mark_release_failed(release: ReleaseRecord, *, summary: str) -> ReleaseRecord:
    return release.model_copy(
        update={
            "status": FAILED,
            "failure_summary": summary,
            "activated_at": None,
        }
    )


def mark_release_gate_blocked(release: ReleaseRecord, *, summary: str) -> ReleaseRecord:
    return release.model_copy(
        update={
            "status": GATE_BLOCKED,
            "failure_summary": summary,
            "activated_at": None,
        }
    )


async def persist_failed_release(
    *,
    store: ActivationStorePort,
    release: ReleaseRecord,
) -> ReleaseRecord:
    await store.save_release(release)
    return release


async def settle_after_agent_reload(
    *,
    store: ActivationStorePort,
    release: ReleaseRecord,
    previous_release_id: str | None,
    correlation_id: str,
    reload_success: bool,
    reload_error: str | None,
    notify_reload: NotifyReload,
    write_local_pointer: WriteLocalPointer,
    utc_now: UtcNow,
) -> ReleaseRecord:
    """Apply compensate / finalize / stale branching after agent reload."""
    current_active = await store.get_active_release_id()
    branch = decide_reload_branch(
        release_id=release.release_id,
        current_active_id=current_active if isinstance(current_active, str) else None,
        reload_success=reload_success,
    )
    if branch == "compensate":
        release = release.model_copy(
            update={
                "status": compensation_target_status(),
                "failure_summary": reload_error or "Agent reload failed",
                "activated_at": None,
            }
        )
        await store.save_release(release)
        await store.set_active_release_id(previous_release_id)
        if previous_release_id:
            write_local_pointer(previous_release_id)
            previous_release = await store.get_release(previous_release_id)
            if isinstance(previous_release, ReleaseRecord):
                await store.save_release(
                    previous_release.model_copy(
                        update={
                            "status": restored_previous_status(),
                            "activated_at": utc_now(),
                        }
                    )
                )
            await notify_reload(previous_release_id, correlation_id)
        return release

    if branch == "finalize":
        release = release.model_copy(
            update={
                "status": "ACTIVE",
                "verified_at": utc_now(),
                "failure_summary": "",
            }
        )
        await store.save_release(release)
        return release

    logger.warning(
        "Release %s reload finished, but active pointer has transitioned to %s.",
        release.release_id,
        current_active,
    )
    return release


__all__ = [
    "mark_release_failed",
    "mark_release_gate_blocked",
    "persist_failed_release",
    "settle_after_agent_reload",
]
