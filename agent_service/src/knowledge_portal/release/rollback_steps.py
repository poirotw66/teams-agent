"""Rollback step helpers extracted from ``rollback_release``."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from knowledge_core.release_gate import ReleaseGateBlockedError, require_release_gate
from knowledge_core.target_manifest import knowledge_release_target_manifest_hash
from knowledge_portal.models import PortalActor, ReleaseRecord, RollbackRequest, utc_now
from knowledge_portal.rbac import PortalPermissionError, can_edit_document

logger = logging.getLogger(__name__)

NotifyReload = Callable[[str, str], Awaitable[tuple[bool, str | None]]]
WriteLocalPointer = Callable[[str], None]
DeactivateOthers = Callable[[str], Awaitable[None]]
CoordinationLock = Callable[..., AbstractAsyncContextManager[Any]]


async def claim_rollback_idempotency(
    ctx: Any,
    *,
    actor: PortalActor,
    request: RollbackRequest,
    idempotency_key: str | None,
) -> tuple[str | None, str | None, ReleaseRecord | None]:
    """Return (scope_key, payload_hash, cached_release) when idempotency applies."""
    if not idempotency_key:
        return None, None, None
    scope_key = (
        f"rollback::{actor.tenant_id or 'default'}::{actor.user_id}::{idempotency_key}"
    )
    payload_hash = hashlib.sha256(
        f"{request.release_id}::{request.reason}".encode()
    ).hexdigest()
    status, cached = await ctx.claim_idempotency(scope_key, payload_hash)
    if status == "CACHED" and cached is not None:
        if isinstance(cached, dict):
            return scope_key, payload_hash, ReleaseRecord.model_validate(cached)
        return scope_key, payload_hash, cached
    return scope_key, payload_hash, None


async def assert_rollback_unit_scope(
    ctx: Any,
    *,
    actor: PortalActor,
    target_manifest: dict[str, str],
    prev_manifest: dict[str, str],
) -> None:
    """Unit managers cannot roll back releases that touch other units' documents."""
    if actor.role == "PLATFORM":
        return
    affected_doc_ids = set(target_manifest.keys()) | set(prev_manifest.keys())
    for doc_id in affected_doc_ids:
        doc = await ctx.repository.get_document(doc_id)
        if doc and not can_edit_document(
            actor, doc.owner_unit_id, doc.created_by, tenant_id=doc.tenant_id
        ):
            raise PortalPermissionError(
                "Global rollback affects documents from other units. "
                "Only platform administrators can perform global rollbacks."
            )


async def sync_documents_to_rollback_manifest(
    ctx: Any,
    *,
    actor: PortalActor,
    target_manifest: dict[str, str],
    prev_manifest: dict[str, str],
) -> None:
    """Align repository document records with the restored release manifest."""
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
                await ctx.repository.save_document(doc.model_copy(update=update_fields))

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
            await ctx.repository.save_document(doc.model_copy(update=update_fields))


async def activate_rollback_target(
    ctx: Any,
    *,
    actor: PortalActor,
    target: ReleaseRecord,
    target_manifest: dict[str, str],
    prev_manifest: dict[str, str],
    correlation_id: str,
    deactivate_others: DeactivateOthers,
    notify_reload: NotifyReload,
    write_local_pointer: WriteLocalPointer,
) -> tuple[ReleaseRecord, bool]:
    """Gate-check, point active release, sync docs, and settle reload status."""
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
    rolled_back = target.model_copy(update={"status": "DEPLOYING", "activated_at": utc_now()})
    await ctx.repository.save_release(rolled_back)
    await sync_documents_to_rollback_manifest(
        ctx,
        actor=actor,
        target_manifest=target_manifest,
        prev_manifest=prev_manifest,
    )

    reload_success, reload_error = await notify_reload(target.release_id, correlation_id)
    current_active = await ctx.repository.get_active_release_id()
    if current_active == target.release_id:
        if reload_success:
            rolled_back = rolled_back.model_copy(
                update={"status": "ACTIVE", "verified_at": utc_now(), "failure_summary": ""}
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
    return rolled_back, reload_success
