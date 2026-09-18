"""Manual agent-sync command for the active (or initial failed) release.

Extracted from ``ReleaseService.sync_agent_release``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from knowledge_portal.models import PortalActor, ReleaseRecord, utc_now
from knowledge_portal.rbac import ensure_can_publish, ensure_not_found

from .transitions import RELOAD_FAILED

logger = logging.getLogger(__name__)

CoordinationLock = Callable[..., AbstractAsyncContextManager[Any]]
NotifyReload = Callable[[str, str], Awaitable[tuple[bool, str | None]]]
RequireAllowed = Callable[..., None]
WriteLocalPointer = Callable[[str], None]
DeactivateOthers = Callable[[str], Awaitable[None]]


class SyncContext(Protocol):
    """Subset of portal context required by agent sync."""

    repository: Any

    async def audit(self, **kwargs: Any) -> None:
        ...


async def sync_agent_release(
    *,
    ctx: SyncContext,
    actor: PortalActor,
    release_id: str,
    correlation_id: str,
    coordination_lock: CoordinationLock,
    require_allowed: RequireAllowed,
    notify_reload: NotifyReload,
    write_local_pointer: WriteLocalPointer,
    deactivate_others: DeactivateOthers,
) -> ReleaseRecord:
    ensure_can_publish(actor)
    release = await ctx.repository.get_release(release_id)
    ensure_not_found("release", release_id, release)
    require_allowed(release)
    active_id = await ctx.repository.get_active_release_id()
    is_initial_failed = active_id is None and release.status == RELOAD_FAILED
    if release_id != active_id and not is_initial_failed:
        raise ValueError(
            f"Cannot sync release '{release_id}' because it is not the current active release ('{active_id}'). Use rollback to switch versions."
        )

    reload_success, reload_error = await notify_reload(release_id, correlation_id)
    async with coordination_lock("sync_agent"):
        current_active = await ctx.repository.get_active_release_id()
        if current_active != release_id and not is_initial_failed:
            logger.warning(
                "Agent reload completed for release %s, but active release has transitioned to %s; discarding stale state mutation.",
                release_id,
                current_active,
            )
            return release

        if reload_success:
            await ctx.repository.set_active_release_id(release_id)
            write_local_pointer(release_id)
            updated = release.model_copy(
                update={
                    "status": "ACTIVE",
                    "verified_at": utc_now(),
                    "failure_summary": "",
                }
            )
            await deactivate_others(release_id)
        else:
            updated = release.model_copy(
                update={
                    "status": "RELOAD_FAILED",
                    "failure_summary": reload_error or "Agent reload failed",
                }
            )
        await ctx.repository.save_release(updated)

    await ctx.audit(
        actor=actor,
        action="release.sync_agent",
        target_type="release",
        target_id=release_id,
        correlation_id=correlation_id,
        reason=f"Manual agent sync: {'SUCCESS' if reload_success else 'FAILURE'}",
        result="SUCCESS" if reload_success else "FAILURE",
        metadata={"reloadError": reload_error} if reload_error else {},
    )
    return updated


__all__ = ["SyncContext", "sync_agent_release"]
