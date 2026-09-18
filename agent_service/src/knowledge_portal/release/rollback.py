"""Rollback command for restoring a previously verified release.

Extracted from ``ReleaseService.rollback_release`` without changing gate,
permission, document-sync, or reload settlement behavior.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from knowledge_core.release_gate import ReleaseGateBlockedError, require_release_gate
from knowledge_core.target_manifest import knowledge_release_target_manifest_hash
from knowledge_portal.models import PortalActor, ReleaseRecord, RollbackRequest, utc_now
from knowledge_portal.rbac import (
    PortalPermissionError,
    can_edit_document,
    ensure_can_publish,
    ensure_not_found,
)

logger = logging.getLogger(__name__)

CoordinationLock = Callable[..., AbstractAsyncContextManager[Any]]
NotifyReload = Callable[[str, str], Awaitable[tuple[bool, str | None]]]
RequireAllowed = Callable[..., None]
WriteLocalPointer = Callable[[str], None]
DeactivateOthers = Callable[[str], Awaitable[None]]


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
    if idempotency_key:
        scope_key = (
            f"rollback::{actor.tenant_id or 'default'}::{actor.user_id}::{idempotency_key}"
        )
        payload_hash = hashlib.sha256(
            f"{request.release_id}::{request.reason}".encode()
        ).hexdigest()
        status, cached = await ctx.claim_idempotency(scope_key, payload_hash)
        if status == "CACHED" and cached is not None:
            if isinstance(cached, dict):
                return ReleaseRecord.model_validate(cached)
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

        # Issue 1: Unit managers cannot perform global rollbacks affecting documents from other units
        if actor.role != "PLATFORM":
            affected_doc_ids = set(target_manifest.keys()) | set(prev_manifest.keys())
            for doc_id in affected_doc_ids:
                doc = await ctx.repository.get_document(doc_id)
                if doc and not can_edit_document(
                    actor, doc.owner_unit_id, doc.created_by, tenant_id=doc.tenant_id
                ):
                    raise PortalPermissionError(
                        "Global rollback affects documents from other units. Only platform administrators can perform global rollbacks."
                    )

        async with coordination_lock("rollback"):
            try:
                require_release_gate(
                    getattr(ctx, "release_gate_checker", None),
                    target_manifest_hash=(
                        target.target_manifest_hash
                        or knowledge_release_target_manifest_hash(release_id=target.release_id)
                    ),
                    target_type="KNOWLEDGE",
                    tenant_id=getattr(actor, "tenant_id", None),
                )
            except ReleaseGateBlockedError as exc:
                raise PortalPermissionError(str(exc)) from exc
            await deactivate_others(target.release_id)
            await ctx.repository.set_active_release_id(target.release_id)
            write_local_pointer(target.release_id)
            rolled_back = target.model_copy(
                update={"status": "DEPLOYING", "activated_at": utc_now()}
            )
            await ctx.repository.save_release(rolled_back)

            # Synchronize repository document records to match target release manifest
            now = utc_now()
            for doc_id in prev_manifest:
                if doc_id not in target_manifest:
                    doc = await ctx.repository.get_document(doc_id)
                    if doc is not None:
                        update_fields: dict[str, Any] = {
                            "current_published_version_id": None,
                            "updated_at": now,
                            "updated_by": actor.user_id,
                        }
                        if doc.status == "PUBLISHED":
                            update_fields["status"] = "UNPUBLISHED"
                        await ctx.repository.save_document(
                            doc.model_copy(update=update_fields)
                        )

            for doc_id, version_id in target_manifest.items():
                doc = await ctx.repository.get_document(doc_id)
                if doc is not None:
                    update_fields = {
                        "current_published_version_id": version_id,
                        "updated_at": now,
                        "updated_by": actor.user_id,
                    }
                    if doc.status == "UNPUBLISHED":
                        update_fields["status"] = "PUBLISHED"
                    await ctx.repository.save_document(
                        doc.model_copy(update=update_fields)
                    )

            reload_success, reload_error = await notify_reload(
                target.release_id, correlation_id
            )
            current_active = await ctx.repository.get_active_release_id()
            if current_active == target.release_id:
                if reload_success:
                    rolled_back = rolled_back.model_copy(
                        update={
                            "status": "ACTIVE",
                            "verified_at": utc_now(),
                            "failure_summary": "",
                        }
                    )
                else:
                    rolled_back = rolled_back.model_copy(
                        update={
                            "status": "RELOAD_FAILED",
                            "failure_summary": reload_error or "Agent reload failed",
                        }
                    )
                await ctx.repository.save_release(rolled_back)
            else:
                logger.warning(
                    "Rollback %s reload finished, but active pointer has transitioned to %s.",
                    target.release_id,
                    current_active,
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
        if idempotency_key:
            await ctx.complete_idempotency(scope_key, payload_hash, rolled_back)
        return rolled_back
    except Exception:
        if idempotency_key:
            await ctx.fail_idempotency(scope_key)
        raise


__all__ = ["RollbackContext", "rollback_release"]
