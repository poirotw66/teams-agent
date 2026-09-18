"""Publish, unpublish, reindex, and published-version collection commands.

Extracted from ``ReleaseService`` so the service facade owns lock wiring and
delegation only. Behavior and error messages are preserved byte-for-byte.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from knowledge_portal.models import (
    DocumentDetailResponse,
    KnowledgeVersionRecord,
    PortalActor,
    PublishRequest,
    ReleaseRecord,
    RemoveDocumentRequest,
    utc_now,
)
from knowledge_portal.rbac import ensure_can_publish, ensure_not_found
from knowledge_portal.repository import new_id

CoordinationLock = Callable[..., AbstractAsyncContextManager[Any]]
ActivateRelease = Callable[..., Awaitable[ReleaseRecord | None]]


class PublishContext(Protocol):
    """Subset of portal context required by publish commands."""

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


class DocumentCommands(Protocol):
    """Document facade methods used by publish / unpublish / remove."""

    async def get_document(
        self, actor: PortalActor, document_id: str
    ) -> DocumentDetailResponse:
        ...

    async def discard_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse | dict[str, str]:
        ...


async def collect_active_published_versions(
    *,
    repository: Any,
    actor: PortalActor,
    exclude_document_ids: set[str] | None = None,
) -> list[KnowledgeVersionRecord]:
    excluded = exclude_document_ids or set()
    published_versions: list[KnowledgeVersionRecord] = []

    active_release_id = await repository.get_active_release_id()
    active_release = (
        await repository.get_release(active_release_id) if active_release_id else None
    )

    if active_release and active_release.manifest:
        for entry in active_release.manifest:
            if entry.document_id in excluded:
                continue
            version = await repository.get_version(entry.version_id)
            if version is not None and version.status == "PUBLISHED":
                published_versions.append(version)
    else:
        # Fallback when no active release exists (e.g. first release):
        # Query with PLATFORM role so cross-unit documents are included.
        admin_actor = (
            actor
            if actor.role == "PLATFORM"
            else PortalActor(
                user_id=actor.user_id,
                display_name=actor.display_name,
                role="PLATFORM",
                owner_unit_ids=(),
                tenant_id=actor.tenant_id,
            )
        )
        for other in await repository.list_documents(actor=admin_actor):
            if other.document_id in excluded:
                continue
            if not other.current_published_version_id:
                continue
            other_version = await repository.get_version(
                other.current_published_version_id
            )
            if other_version is not None and other_version.status == "PUBLISHED":
                published_versions.append(other_version)

    return published_versions


async def _execute_publish(
    *,
    ctx: PublishContext,
    documents: DocumentCommands,
    actor: PortalActor,
    document_id: str,
    request: PublishRequest,
    correlation_id: str,
    activate_release: ActivateRelease,
) -> tuple[ReleaseRecord, Any, Any]:
    detail = await documents.get_document(actor, document_id)
    document = detail.document
    version = await ctx.repository.get_version(request.version_id)
    ensure_not_found("version", request.version_id, version)
    if version.document_id != document_id:
        raise ValueError("Version does not belong to this document.")
    if version.status != "APPROVED":
        raise ValueError("Only approved versions can be published.")
    if (
        ctx.settings.require_dual_approval
        and actor.user_id == version.created_by
        and actor.role != "PLATFORM"
    ):
        raise ValueError("Contributors cannot publish their own approved content.")

    published_versions = await collect_active_published_versions(
        repository=ctx.repository,
        actor=actor,
        exclude_document_ids={document_id},
    )
    published_versions.append(version.model_copy(update={"status": "PUBLISHED"}))

    release = await activate_release(
        actor=actor,
        published_versions=published_versions,
        correlation_id=correlation_id,
        reason=request.reason,
        metadata={"documentId": document_id, "versionId": version.version_id},
    )
    if release is None:
        raise ValueError("Publishing failed to produce an active release.")

    updated_version = version.model_copy(update={"status": "PUBLISHED"})
    updated_document = document.model_copy(
        update={
            "status": "PUBLISHED",
            "current_published_version_id": version.version_id,
            "draft_version_id": None,
            "updated_at": utc_now(),
            "updated_by": actor.user_id,
        }
    )
    await ctx.repository.save_version(updated_version)
    await ctx.repository.save_document(updated_document)
    return release, document, version


async def publish_version(
    *,
    ctx: PublishContext,
    documents: DocumentCommands,
    actor: PortalActor,
    document_id: str,
    request: PublishRequest,
    correlation_id: str,
    idempotency_key: str | None,
    coordination_lock: CoordinationLock,
    activate_release: ActivateRelease,
) -> ReleaseRecord:
    scope_key = ""
    payload_hash = ""
    if idempotency_key:
        scope_key = (
            f"publish::{actor.tenant_id or 'default'}::{actor.user_id}::{idempotency_key}"
        )
        payload_hash = hashlib.sha256(
            f"{document_id}::{request.model_dump_json()}".encode()
        ).hexdigest()
        status, cached = await ctx.claim_idempotency(scope_key, payload_hash)
        if status == "CACHED" and cached is not None:
            if isinstance(cached, dict):
                return ReleaseRecord.model_validate(cached)
            return cached

    try:
        ensure_can_publish(actor)
        async with coordination_lock("publish"):
            release, document, version = await _execute_publish(
                ctx=ctx,
                documents=documents,
                actor=actor,
                document_id=document_id,
                request=request,
                correlation_id=correlation_id,
                activate_release=activate_release,
            )

        await ctx.audit(
            actor=actor,
            action="document.publish",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
            reason=request.reason,
            before={
                "status": document.status,
                "currentPublishedVersionId": document.current_published_version_id,
            },
            after={
                "status": "PUBLISHED",
                "currentPublishedVersionId": version.version_id,
                "releaseId": release.release_id,
            },
            metadata={"versionId": version.version_id, "releaseId": release.release_id},
        )
        if idempotency_key:
            await ctx.complete_idempotency(scope_key, payload_hash, release)
        return release
    except Exception:
        if idempotency_key:
            await ctx.fail_idempotency(scope_key)
        raise


async def unpublish_document(
    *,
    ctx: PublishContext,
    documents: DocumentCommands,
    actor: PortalActor,
    document_id: str,
    request: RemoveDocumentRequest,
    correlation_id: str,
    coordination_lock: CoordinationLock,
    activate_release: ActivateRelease,
) -> DocumentDetailResponse:
    ensure_can_publish(actor)
    async with coordination_lock("unpublish"):
        detail = await documents.get_document(actor, document_id)
        document = detail.document
        if document.status != "PUBLISHED" and not document.current_published_version_id:
            raise ValueError("Only published documents can be unpublished.")

        published_versions = await collect_active_published_versions(
            repository=ctx.repository,
            actor=actor,
            exclude_document_ids={document_id},
        )
        await activate_release(
            actor=actor,
            published_versions=published_versions,
            correlation_id=correlation_id,
            reason=request.reason,
            metadata={"documentId": document_id, "action": "unpublish"},
        )

        now = utc_now()
        updated_document = document.model_copy(
            update={
                "status": "UNPUBLISHED",
                "current_published_version_id": None,
                "updated_at": now,
                "updated_by": actor.user_id,
            }
        )
        await ctx.repository.save_document(updated_document)

    await ctx.audit(
        actor=actor,
        action="document.unpublish",
        target_type="document",
        target_id=document_id,
        correlation_id=correlation_id,
        reason=request.reason,
    )
    return await documents.get_document(actor, document_id)


async def remove_document(
    *,
    documents: DocumentCommands,
    unpublish: Callable[
        [PortalActor, str, RemoveDocumentRequest, str],
        Awaitable[DocumentDetailResponse],
    ],
    actor: PortalActor,
    document_id: str,
    request: RemoveDocumentRequest,
    correlation_id: str,
) -> DocumentDetailResponse | dict[str, str]:
    detail = await documents.get_document(actor, document_id)
    document = detail.document
    if document.current_published_version_id and document.status == "PUBLISHED":
        return await unpublish(actor, document_id, request, correlation_id)
    return await documents.discard_draft(actor, document_id, request, correlation_id)


async def reindex_all_published(
    *,
    repository: Any,
    actor: PortalActor,
    scope_type: str,
    scope_ids: list[str] | None,
    correlation_id: str | None,
    reason: str,
    embedding_model: str | None,
    coordination_lock: CoordinationLock,
    activate_release: ActivateRelease,
) -> ReleaseRecord:
    async with coordination_lock("reindex_knowledge"):
        published_versions = await collect_active_published_versions(
            repository=repository,
            actor=actor,
        )
        if scope_type == "DOCUMENTS" and scope_ids:
            published_versions = [v for v in published_versions if v.document_id in scope_ids]
        release = await activate_release(
            actor=actor,
            published_versions=published_versions,
            correlation_id=correlation_id or new_id("corr"),
            reason=reason,
            embedding_model=embedding_model,
        )
        return release


__all__ = [
    "DocumentCommands",
    "PublishContext",
    "collect_active_published_versions",
    "publish_version",
    "reindex_all_published",
    "remove_document",
    "unpublish_document",
]
