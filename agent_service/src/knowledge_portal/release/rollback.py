"""Rollback command for restoring a previously verified release.

Extracted from ``ReleaseService.rollback_release`` without changing gate,
permission, document-sync, or reload settlement behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from knowledge_portal.models import PortalActor, ReleaseRecord, RollbackRequest
from knowledge_portal.rbac import ensure_can_publish, ensure_not_found

from .rollback_steps import (
    CoordinationLock,
    DeactivateOthers,
    NotifyReload,
    WriteLocalPointer,
    activate_rollback_target,
    assert_rollback_unit_scope,
    claim_rollback_idempotency,
)

RequireAllowed = Callable[..., None]


class RollbackContext(Protocol):
    """Subset of portal context required by rollback."""

    repository: Any
    settings: Any

    async def claim_idempotency(
        self, key: str, payload_hash: str
    ) -> tuple[str, Any | None]:
        ...

    async def complete_idempotency(
        self, key: str, payload_hash: str, response: Any
    ) -> None:
        ...

    async def fail_idempotency(self, key: str) -> None:
        ...

    async def audit(self, **kwargs: Any) -> None:
        ...


async def rollback_release(
    *,
    ctx: RollbackContext,
    actor: PortalActor,
    request: RollbackRequest,
    correlation_id: str,
    idempotency_key: str | None,
    coordination_lock: CoordinationLock,
    require_allowed: RequireAllowed,
    notify_reload: NotifyReload,
    write_local_pointer: WriteLocalPointer,
    deactivate_others: DeactivateOthers,
) -> ReleaseRecord:
    scope_key, payload_hash, cached = await claim_rollback_idempotency(
        ctx, actor=actor, request=request, idempotency_key=idempotency_key
    )
    if cached is not None:
        return cached

    try:
        ensure_can_publish(actor)
        target = await ctx.repository.get_release(request.release_id)
        ensure_not_found("release", request.release_id, target)
        require_allowed(target, require_verified=True)
        previous_active_id = await ctx.repository.get_active_release_id()
        previous_release = (
            await ctx.repository.get_release(previous_active_id)
            if previous_active_id
            else None
        )
        target_manifest = {entry.document_id: entry.version_id for entry in target.manifest}
        prev_manifest = (
            {entry.document_id: entry.version_id for entry in previous_release.manifest}
            if previous_release
            else {}
        )
        await assert_rollback_unit_scope(
            ctx,
            actor=actor,
            target_manifest=target_manifest,
            prev_manifest=prev_manifest,
        )

        async with coordination_lock("rollback"):
            rolled_back, reload_success = await activate_rollback_target(
                ctx,
                actor=actor,
                target=target,
                target_manifest=target_manifest,
                prev_manifest=prev_manifest,
                correlation_id=correlation_id,
                deactivate_others=deactivate_others,
                notify_reload=notify_reload,
                write_local_pointer=write_local_pointer,
            )

        await ctx.audit(
            actor=actor,
            action="release.rollback",
            target_type="release",
            target_id=target.release_id,
            correlation_id=correlation_id,
            reason=request.reason,
            before={"activeReleaseId": previous_active_id},
            after={"activeReleaseId": target.release_id},
            metadata={
                "previousReleaseId": previous_active_id,
                "reloadStatus": "SUCCESS" if reload_success else "FAILURE",
            },
        )
        if idempotency_key and scope_key and payload_hash:
            await ctx.complete_idempotency(scope_key, payload_hash, rolled_back)
        return rolled_back
    except Exception:
        if idempotency_key and scope_key:
            await ctx.fail_idempotency(scope_key)
        raise


__all__ = ["RollbackContext", "rollback_release"]
