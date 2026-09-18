"""Promote an existing candidate release after a release-gate pass.

Extracted from ``ReleaseService.promote_candidate_release`` without changing
gate-block persistence, activation, or post-reload settlement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from agent_service.release_gate import ReleaseGateBlockedError, require_release_gate
from agent_service.target_manifest import knowledge_release_target_manifest_hash
from knowledge_portal.models import PortalActor, ReleaseRecord, utc_now
from knowledge_portal.rbac import PortalPermissionError, ensure_can_publish, ensure_not_found
from knowledge_portal.repository import new_id

from .activation import settle_promote_after_agent_reload
from .transitions import can_promote, promote_rejection_message

CoordinationLock = Callable[..., AbstractAsyncContextManager[Any]]
NotifyReload = Callable[[str, str], Awaitable[tuple[bool, str | None]]]
RequireAllowed = Callable[..., None]
WriteLocalPointer = Callable[[str], None]
DeactivateOthers = Callable[[str], Awaitable[None]]


class PromoteContext(Protocol):
    """Subset of portal context required by promote."""

    repository: Any
    settings: Any

    async def audit(self, **kwargs: Any) -> None:
        ...


async def promote_candidate_release(
    *,
    ctx: PromoteContext,
    actor: PortalActor,
    release_id: str,
    correlation_id: str | None,
    reason: str,
    coordination_lock: CoordinationLock,
    require_allowed: RequireAllowed,
    notify_reload: NotifyReload,
    write_local_pointer: WriteLocalPointer,
    deactivate_others: DeactivateOthers,
) -> ReleaseRecord:
    """Activate an existing candidate release without rebuilding the corpus.

    Used after a release was persisted as ``GATE_BLOCKED`` (or otherwise built
    but not activated). Reuses the same release ID and target_manifest_hash so
    a later PASS decision can promote the identical candidate.
    """

    ensure_can_publish(actor)
    target = await ctx.repository.get_release(release_id)
    ensure_not_found("release", release_id, target)
    require_allowed(target)
    if not can_promote(target.status):
        raise PortalPermissionError(
            promote_rejection_message(release_id=release_id, status=target.status)
        )

    corr = correlation_id or new_id("corr")
    gate_hash = target.target_manifest_hash or knowledge_release_target_manifest_hash(
        release_id=target.release_id
    )
    try:
        require_release_gate(
            getattr(ctx, "release_gate_checker", None),
            target_manifest_hash=gate_hash,
            target_type="KNOWLEDGE",
            tenant_id=getattr(actor, "tenant_id", None),
        )
    except ReleaseGateBlockedError as exc:
        blocked = target.model_copy(
            update={
                "status": "GATE_BLOCKED",
                "failure_summary": str(exc),
                "activated_at": None,
                "target_manifest_hash": gate_hash,
            }
        )
        await ctx.repository.save_release(blocked)
        await ctx.audit(
            actor=actor,
            action="release.gate_blocked",
            target_type="release",
            target_id=target.release_id,
            correlation_id=corr,
            reason=str(exc),
            result="FAILURE",
        )
        raise PortalPermissionError(str(exc)) from exc

    async with coordination_lock("promote_candidate"):
        previous_active_id = await ctx.repository.get_active_release_id()
        release = target.model_copy(
            update={
                "status": "DEPLOYING",
                "activated_at": utc_now(),
                "approved_by": actor.user_id,
                "failure_summary": "",
                "target_manifest_hash": gate_hash,
            }
        )
        await deactivate_others(release.release_id)
        await ctx.repository.save_release(release)
        await ctx.repository.set_active_release_id(release.release_id)
        write_local_pointer(release.release_id)

        reload_success, reload_error = await notify_reload(release.release_id, corr)
        release = await settle_promote_after_agent_reload(
            store=ctx.repository,
            release=release,
            previous_active_id=previous_active_id,
            correlation_id=corr,
            reload_success=reload_success,
            reload_error=reload_error,
            notify_reload=notify_reload,
            write_local_pointer=write_local_pointer,
            utc_now=utc_now,
        )

        await ctx.audit(
            actor=actor,
            action="release.promote_candidate",
            target_type="release",
            target_id=release.release_id,
            correlation_id=corr,
            reason=reason,
            metadata={
                "reloadStatus": "SUCCESS" if reload_success else "FAILURE",
                "targetManifestHash": gate_hash,
            },
        )
        return release


__all__ = ["PromoteContext", "promote_candidate_release"]
