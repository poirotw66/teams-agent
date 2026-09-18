"""Published-document revision workflow for VersionService."""

from __future__ import annotations

from typing import Protocol

from ..draft_assets import DraftAssetStore, slug_from_title
from ..models import (
    DocumentDetailResponse,
    KnowledgeVersionRecord,
    PortalActor,
    ValidationSummary,
    new_etag,
    utc_now,
)
from ..original_assets import OriginalAssetStore
from ..rbac import ensure_can_edit
from ..repository import new_id
from .context import PortalServiceContext


class DocumentLookup(Protocol):
    async def get_document(
        self, actor: PortalActor, document_id: str
    ) -> DocumentDetailResponse: ...


def build_revision_version(
    *,
    actor: PortalActor,
    document_id: str,
    published: KnowledgeVersionRecord,
    version_id: str,
    asset_slug: str,
    change_reason: str,
) -> KnowledgeVersionRecord:
    now = utc_now()
    return KnowledgeVersionRecord(
        version_id=version_id,
        document_id=document_id,
        version_number=published.version_number + 1,
        source_type=published.source_type,
        content_hash=published.content_hash,
        canonical_content=published.canonical_content,
        change_summary=f"Revision {published.version_number + 1}",
        change_reason=change_reason,
        effective_at=published.effective_at,
        review_due_at=published.review_due_at,
        audience_type=published.audience_type,
        audience_group_ids=published.audience_group_ids,
        source_aliases=published.source_aliases,
        content_state=published.content_state,
        expires_at=published.expires_at,
        applicable_environments=published.applicable_environments,
        owner_unit_id=published.owner_unit_id,
        business_contact=published.business_contact,
        category=published.category,
        summary=published.summary,
        title=published.title,
        asset_slug=asset_slug,
        status="DRAFT",
        validation_summary=ValidationSummary(issues=[]),
        parse_preview=published.parse_preview,
        original_asset_name=published.original_asset_name,
        original_asset_sha256=published.original_asset_sha256,
        original_asset_content_type=published.original_asset_content_type,
        original_asset_size=published.original_asset_size,
        etag=new_etag(published.content_hash, published.version_number + 1),
        created_at=now,
        created_by=actor.user_id,
    )


async def start_revision(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    document_id: str,
    correlation_id: str,
    change_reason: str = "Start a new revision from the published version.",
) -> DocumentDetailResponse:
    detail = await documents.get_document(actor, document_id)
    document = detail.document
    ensure_can_edit(
        actor,
        document.owner_unit_id,
        document.created_by,
        tenant_id=document.tenant_id,
    )
    if document.status != "PUBLISHED" or detail.published_version is None:
        raise ValueError("Only published documents can start a new revision.")
    if document.draft_version_id is not None:
        raise ValueError("Document already has an open draft.")

    published = detail.published_version
    now = utc_now()
    version_id = new_id("ver")
    asset_slug = published.asset_slug or slug_from_title(published.title)
    DraftAssetStore(ctx.settings).copy_bundle(
        source_document_id=document_id,
        source_version_id=published.version_id,
        target_document_id=document_id,
        target_version_id=version_id,
        asset_slug=asset_slug,
    )
    version = build_revision_version(
        actor=actor,
        document_id=document_id,
        published=published,
        version_id=version_id,
        asset_slug=asset_slug,
        change_reason=change_reason,
    )
    OriginalAssetStore(ctx.settings).copy_version(
        document_id=document_id,
        source_version_id=published.version_id,
        target_version_id=version_id,
        filename=published.original_asset_name,
    )
    updated_document = document.model_copy(
        update={
            "draft_version_id": version_id,
            "status": "DRAFT",
            "updated_at": now,
            "updated_by": actor.user_id,
            "etag": new_etag(document.document_id, published.version_number + 1),
        }
    )
    await ctx.repository.save_version(version)
    await ctx.repository.save_document(updated_document)
    await ctx.audit(
        actor=actor,
        action="document.start_revision",
        target_type="document",
        target_id=document_id,
        correlation_id=correlation_id,
        before={"status": document.status, "draftVersionId": document.draft_version_id},
        after={
            "status": updated_document.status,
            "draftVersionId": updated_document.draft_version_id,
        },
    )
    return await documents.get_document(actor, document_id)
