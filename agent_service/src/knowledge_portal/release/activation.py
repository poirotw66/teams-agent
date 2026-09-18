"""Activation saga steps that compose release ports.

Extracted from ``ReleaseService._activate_release`` and related settle /
deactivate helpers so the service facade owns command orchestration only.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TypeVar

from agent_service.knowledge_release import write_active_release_pointer
from knowledge_core.release_gate import ReleaseGateBlockedError, require_release_gate
from knowledge_core.target_manifest import knowledge_release_target_manifest_hash
from knowledge_portal.models import (
    KnowledgeVersionRecord,
    PortalActor,
    ReleaseRecord,
)
from knowledge_portal.publisher import ReleaseBuildError
from knowledge_portal.rbac import PortalPermissionError

from .coordinator import (
    compensation_target_status,
    deactivated_status,
    decide_reload_branch,
    restored_previous_status,
    should_mark_rolled_back,
)
from .ports import ActivationStorePort
from .transitions import FAILED, GATE_BLOCKED

logger = logging.getLogger(__name__)

ReleaseT = TypeVar("ReleaseT", bound=ReleaseRecord)
NotifyReload = Callable[[str, str], Awaitable[tuple[bool, str | None]]]
WriteLocalPointer = Callable[[str], None]
UtcNow = Callable[[], datetime]
AuditFn = Callable[..., Awaitable[Any]]


class ReleaseBuilder(Protocol):
    def build_release(
        self,
        *,
        release_id: str,
        published_versions: Sequence[KnowledgeVersionRecord],
        created_by: str,
        previous_release_id: str | None,
        embedding_model: str | None = None,
        tenant_id: str | None = None,
    ) -> ReleaseRecord:
        ...


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


def write_local_active_pointer(
    *,
    release_artifact_dir: str | Path,
    release_gcs_bucket: str | None,
    release_id: str,
) -> None:
    """Persist the local active-release pointer when GCS is not configured."""
    if release_gcs_bucket:
        return
    write_active_release_pointer(release_artifact_dir, release_id)


async def deactivate_other_releases(
    store: ActivationStorePort,
    active_release_id: str,
) -> None:
    """Mark superseded releases ROLLED_BACK when another release activates."""
    for item in await store.list_releases():
        release_id = getattr(item, "release_id", None)
        status = getattr(item, "status", None)
        if release_id == active_release_id:
            continue
        if not isinstance(status, str) or not should_mark_rolled_back(status):
            continue
        if not hasattr(item, "model_copy"):
            continue
        await store.save_release(
            item.model_copy(update={"status": deactivated_status()})
        )


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


async def settle_promote_after_agent_reload(
    *,
    store: ActivationStorePort,
    release: ReleaseRecord,
    previous_active_id: str | None,
    correlation_id: str,
    reload_success: bool,
    reload_error: str | None,
    notify_reload: NotifyReload,
    write_local_pointer: WriteLocalPointer,
    utc_now: UtcNow,
) -> ReleaseRecord:
    """Settle promote-candidate after reload (preserves promote-specific compensate)."""
    current_active = await store.get_active_release_id()
    if current_active != release.release_id:
        return release

    if reload_success:
        release = release.model_copy(
            update={
                "status": "ACTIVE",
                "verified_at": utc_now(),
                "failure_summary": "",
            }
        )
    else:
        release = release.model_copy(
            update={
                "status": "RELOAD_FAILED",
                "activated_at": None,
                "failure_summary": reload_error or "Agent reload failed",
            }
        )
        await store.set_active_release_id(previous_active_id)
        if previous_active_id:
            previous = await store.get_release(previous_active_id)
            if previous is not None and hasattr(previous, "model_copy"):
                await store.save_release(
                    previous.model_copy(update={"status": "ACTIVE"})
                )
            write_local_pointer(previous_active_id)
            await notify_reload(previous_active_id, correlation_id)
    await store.save_release(release)
    return release


async def build_deploying_candidate(
    *,
    publisher: ReleaseBuilder,
    actor: PortalActor,
    published_versions: list[KnowledgeVersionRecord],
    release_id: str,
    previous_release_id: str | None,
    embedding_model: str | None,
    correlation_id: str,
    audit: AuditFn,
    utc_now: UtcNow,
) -> ReleaseRecord:
    """Build release artifacts and mark the candidate DEPLOYING."""
    try:
        release = publisher.build_release(
            release_id=release_id,
            published_versions=published_versions,
            created_by=actor.user_id,
            previous_release_id=previous_release_id,
            embedding_model=embedding_model,
            tenant_id=actor.tenant_id,
        )
    except ReleaseBuildError as exc:
        await audit(
            actor=actor,
            action="release.failed",
            target_type="release",
            target_id=release_id,
            correlation_id=correlation_id,
            reason=str(exc),
            result="FAILURE",
        )
        raise
    return release.model_copy(
        update={
            "status": "DEPLOYING",
            "activated_at": utc_now(),
            "approved_by": actor.user_id,
            "target_manifest_hash": release.target_manifest_hash
            or knowledge_release_target_manifest_hash(release_id=release.release_id),
        }
    )


async def enforce_activation_gate(
    *,
    store: ActivationStorePort,
    release: ReleaseRecord,
    actor: PortalActor,
    correlation_id: str,
    release_gate_checker: object | None,
    audit: AuditFn,
    require_allowed: Callable[[ReleaseRecord], None],
) -> None:
    """Run allow-list and release-gate checks before pointer mutation."""
    try:
        require_allowed(release)
    except PortalPermissionError as exc:
        failed = mark_release_failed(release, summary=str(exc))
        await store.save_release(failed)
        await audit(
            actor=actor,
            action="release.failed",
            target_type="release",
            target_id=release.release_id,
            correlation_id=correlation_id,
            reason=str(exc),
            result="FAILURE",
        )
        raise
    gate_hash = release.target_manifest_hash or knowledge_release_target_manifest_hash(
        release_id=release.release_id
    )
    # Gate must run before mutating other release statuses or the active pointer.
    try:
        require_release_gate(
            release_gate_checker,
            target_manifest_hash=gate_hash,
            target_type="KNOWLEDGE",
            tenant_id=getattr(actor, "tenant_id", None),
        )
    except ReleaseGateBlockedError as exc:
        blocked = mark_release_gate_blocked(release, summary=str(exc))
        await store.save_release(blocked)
        await audit(
            actor=actor,
            action="release.gate_blocked",
            target_type="release",
            target_id=release.release_id,
            correlation_id=correlation_id,
            reason=str(exc),
            result="FAILURE",
        )
        raise PortalPermissionError(str(exc)) from exc


async def persist_activation_source_records(
    *,
    store: ActivationStorePort,
    release: ReleaseRecord,
    actor: PortalActor,
    correlation_id: str,
    portal_settings: object,
    source_catalog_writer: object | None,
    audit: AuditFn,
) -> None:
    """Persist SourceRecords before activating and deactivating older releases."""
    try:
        from knowledge_portal.source_record_publish import persist_release_source_records

        saved = await persist_release_source_records(
            portal_settings,
            release,
            writer=source_catalog_writer,
        )
        if saved:
            logger.info(
                "Release %s SourceRecords persisted: %s",
                release.release_id,
                saved,
            )
    except Exception as exc:
        logger.exception(
            "Failed persisting SourceRecords for release %s",
            release.release_id,
        )
        failed = mark_release_failed(
            release,
            summary=f"Failed persisting SourceRecords: {exc}",
        )
        await store.save_release(failed)
        await audit(
            actor=actor,
            action="release.source_records_failed",
            target_type="release",
            target_id=release.release_id,
            correlation_id=correlation_id,
            reason=str(exc),
            result="FAILURE",
        )
        raise RuntimeError(f"Failed persisting SourceRecords for release: {exc}") from exc


async def commit_active_release_pointer(
    *,
    store: ActivationStorePort,
    release: ReleaseRecord,
    write_local_pointer: WriteLocalPointer,
) -> None:
    """Deactivate peers, persist the candidate, and advance the active pointer."""
    await deactivate_other_releases(store, release.release_id)
    await store.save_release(release)
    await store.set_active_release_id(release.release_id)
    write_local_pointer(release.release_id)


async def activate_release(
    *,
    store: ActivationStorePort,
    publisher: ReleaseBuilder,
    actor: PortalActor,
    published_versions: list[KnowledgeVersionRecord],
    correlation_id: str,
    reason: str,
    release_id: str,
    metadata: dict[str, Any] | None = None,
    embedding_model: str | None = None,
    release_gate_checker: object | None,
    source_catalog_writer: object | None,
    portal_settings: object,
    audit: AuditFn,
    require_allowed: Callable[[ReleaseRecord], None],
    notify_reload: NotifyReload,
    write_local_pointer: WriteLocalPointer,
    utc_now: UtcNow,
) -> ReleaseRecord:
    """Build, gate, persist sources, activate pointer, reload, and settle."""
    previous = await store.get_active_release_id()
    previous_release_id = previous if isinstance(previous, str) else None
    release = await build_deploying_candidate(
        publisher=publisher,
        actor=actor,
        published_versions=published_versions,
        release_id=release_id,
        previous_release_id=previous_release_id,
        embedding_model=embedding_model,
        correlation_id=correlation_id,
        audit=audit,
        utc_now=utc_now,
    )
    await enforce_activation_gate(
        store=store,
        release=release,
        actor=actor,
        correlation_id=correlation_id,
        release_gate_checker=release_gate_checker,
        audit=audit,
        require_allowed=require_allowed,
    )
    await persist_activation_source_records(
        store=store,
        release=release,
        actor=actor,
        correlation_id=correlation_id,
        portal_settings=portal_settings,
        source_catalog_writer=source_catalog_writer,
        audit=audit,
    )
    await commit_active_release_pointer(
        store=store,
        release=release,
        write_local_pointer=write_local_pointer,
    )
    reload_success, reload_error = await notify_reload(release.release_id, correlation_id)
    release = await settle_after_agent_reload(
        store=store,
        release=release,
        previous_release_id=previous_release_id,
        correlation_id=correlation_id,
        reload_success=reload_success,
        reload_error=reload_error,
        notify_reload=notify_reload,
        write_local_pointer=write_local_pointer,
        utc_now=utc_now,
    )
    await audit(
        actor=actor,
        action="release.activate",
        target_type="release",
        target_id=release.release_id,
        correlation_id=correlation_id,
        reason=reason,
        metadata=_activation_audit_metadata(metadata, reload_success, reload_error),
    )
    return release


def _activation_audit_metadata(
    metadata: dict[str, Any] | None,
    reload_success: bool,
    reload_error: str | None,
) -> dict[str, Any]:
    audit_meta = dict(metadata or {})
    audit_meta["reloadStatus"] = "SUCCESS" if reload_success else "FAILURE"
    if reload_error:
        audit_meta["reloadError"] = reload_error
    return audit_meta


__all__ = [
    "activate_release",
    "build_deploying_candidate",
    "commit_active_release_pointer",
    "deactivate_other_releases",
    "enforce_activation_gate",
    "mark_release_failed",
    "mark_release_gate_blocked",
    "persist_activation_source_records",
    "persist_failed_release",
    "settle_after_agent_reload",
    "settle_promote_after_agent_reload",
    "write_local_active_pointer",
]

