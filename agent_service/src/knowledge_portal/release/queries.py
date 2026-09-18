"""Read-side release listing and compare helpers.

Extracted from ``ReleaseService.list_releases`` and ``compare_releases``.
"""

from __future__ import annotations

from typing import Any, Protocol

from knowledge_portal.models import (
    PortalActor,
    ReleaseCompareResponse,
    ReleaseDocumentChange,
    ReleaseManifestEntry,
    ReleaseRecord,
)
from knowledge_portal.rbac import can_view_document, ensure_not_found
from knowledge_portal.role_capabilities import ensure_can_list_releases


class QueryContext(Protocol):
    """Subset of portal context required by release queries."""

    repository: Any


async def list_releases(*, ctx: QueryContext, actor: PortalActor) -> list[ReleaseRecord]:
    ensure_can_list_releases(actor)
    releases = await ctx.repository.list_releases()
    if actor.role == "PLATFORM" or not actor.owner_unit_ids:
        return releases

    sanitized_releases: list[ReleaseRecord] = []
    for release in releases:
        sanitized_manifest: list[ReleaseManifestEntry] = []
        for entry in release.manifest:
            doc = await ctx.repository.get_document(entry.document_id)
            if doc and can_view_document(
                actor, doc.owner_unit_id, doc.created_by, tenant_id=doc.tenant_id
            ):
                sanitized_manifest.append(entry)
            else:
                sanitized_manifest.append(
                    entry.model_copy(update={"title": "[Restricted Document]"})
                )
        sanitized_releases.append(release.model_copy(update={"manifest": sanitized_manifest}))
    return sanitized_releases


async def compare_releases(
    *,
    ctx: QueryContext,
    actor: PortalActor,
    target_release_id: str,
) -> ReleaseCompareResponse:
    ensure_can_list_releases(actor)
    target = await ctx.repository.get_release(target_release_id)
    ensure_not_found("release", target_release_id, target)
    current_id = await ctx.repository.get_active_release_id()
    current = await ctx.repository.get_release(current_id) if current_id else None

    current_manifest = {
        entry.document_id: entry for entry in (current.manifest if current else [])
    }
    target_manifest = {entry.document_id: entry for entry in target.manifest}

    changes: list[ReleaseDocumentChange] = []
    for doc_id, entry in target_manifest.items():
        doc = await ctx.repository.get_document(doc_id)
        is_visible = (
            actor.role == "PLATFORM"
            or not actor.owner_unit_ids
            or (
                doc is not None
                and can_view_document(
                    actor, doc.owner_unit_id, doc.created_by, tenant_id=doc.tenant_id
                )
            )
        )
        title = entry.title if is_visible else "[Restricted Document]"
        current_entry = current_manifest.get(doc_id)
        if current_entry is None:
            changes.append(
                ReleaseDocumentChange(
                    document_id=doc_id,
                    title=title,
                    change_type="ADDED",
                    target_version_id=entry.version_id,
                )
            )
        elif current_entry.version_id != entry.version_id:
            changes.append(
                ReleaseDocumentChange(
                    document_id=doc_id,
                    title=title,
                    change_type="UPDATED",
                    current_version_id=current_entry.version_id,
                    target_version_id=entry.version_id,
                )
            )
    for doc_id, entry in current_manifest.items():
        if doc_id not in target_manifest:
            doc = await ctx.repository.get_document(doc_id)
            is_visible = (
                actor.role == "PLATFORM"
                or not actor.owner_unit_ids
                or (
                    doc is not None
                    and can_view_document(
                        actor, doc.owner_unit_id, doc.created_by, tenant_id=doc.tenant_id
                    )
                )
            )
            title = entry.title if is_visible else "[Restricted Document]"
            changes.append(
                ReleaseDocumentChange(
                    document_id=doc_id,
                    title=title,
                    change_type="REMOVED",
                    current_version_id=entry.version_id,
                )
            )

    target_is_older = False
    if current is not None and current.created_at and target.created_at:
        target_is_older = target.created_at < current.created_at

    return ReleaseCompareResponse(
        current_release_id=current_id,
        target_release_id=target_release_id,
        target_is_older=target_is_older,
        document_count_delta=len(target.manifest) - len(current_manifest),
        changes=changes,
    )


__all__ = ["QueryContext", "compare_releases", "list_releases"]
