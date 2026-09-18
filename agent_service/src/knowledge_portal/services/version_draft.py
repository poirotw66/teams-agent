"""Draft update, validation, and discard workflows for VersionService."""

from __future__ import annotations

from typing import Any, Protocol

from ..models import (
    DocumentDetailResponse,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    RemoveDocumentRequest,
    UpdateDraftRequest,
    ValidationSummary,
    new_etag,
    utc_now,
)
from ..original_assets import OriginalAssetStore
from ..rbac import ensure_can_edit, ensure_can_remove_document, ensure_not_found
from ..repository import VersionConflictError
from ..validation import (
    build_front_matter_markdown,
    build_parse_preview,
    content_hash,
    validate_draft,
)
from .context import PortalServiceContext


class DocumentLookup(Protocol):
    async def get_document(
        self, actor: PortalActor, document_id: str
    ) -> DocumentDetailResponse: ...


async def load_editable_draft(
    *,
    documents: DocumentLookup,
    repository: Any,
    actor: PortalActor,
    document_id: str,
    request: UpdateDraftRequest,
) -> tuple[KnowledgeDocumentRecord, KnowledgeVersionRecord]:
    detail = await documents.get_document(actor, document_id)
    document = detail.document
    ensure_can_edit(
        actor,
        document.owner_unit_id,
        document.created_by,
        tenant_id=document.tenant_id,
    )
    if document.status not in {"DRAFT", "CHANGES_REQUESTED", "APPROVED"}:
        raise ValueError("Only draft documents can be edited.")
    if document.etag != request.etag:
        raise VersionConflictError(document_id)
    if not document.draft_version_id:
        raise ValueError("Document has no editable draft version.")

    version = await repository.get_version(document.draft_version_id)
    ensure_not_found("version", document.draft_version_id, version)
    if version.status not in {"DRAFT", "CHANGES_REQUESTED", "APPROVED"}:
        raise ValueError("Draft version is locked for editing.")
    return document, version


def draft_version_update_fields(
    *,
    request: UpdateDraftRequest,
    version: KnowledgeVersionRecord,
    canonical: str,
    digest: str,
    validation: Any,
    original_meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": request.title,
        "summary": request.summary,
        "category": request.category,
        "owner_unit_id": request.owner_unit_id,
        "business_contact": request.business_contact,
        "audience_type": request.audience_type,
        "audience_group_ids": request.audience_group_ids,
        "source_aliases": request.source_aliases,
        "content_state": request.content_state,
        "expires_at": request.expires_at,
        "applicable_environments": request.applicable_environments,
        "change_summary": request.change_summary,
        "change_reason": request.change_reason,
        "effective_at": request.effective_at,
        "review_due_at": request.review_due_at,
        "canonical_content": canonical,
        "content_hash": digest,
        "validation_summary": validation,
        "parse_preview": build_parse_preview(canonical, request.title),
        "etag": new_etag(digest, version.version_number + 1),
        "status": "DRAFT",
        **original_meta,
    }


def draft_document_update_fields(
    *,
    request: UpdateDraftRequest,
    document: KnowledgeDocumentRecord,
    version: KnowledgeVersionRecord,
    actor: PortalActor,
) -> dict[str, Any]:
    return {
        "title": request.title,
        "summary": request.summary,
        "category": request.category,
        "owner_unit_id": request.owner_unit_id,
        "business_contact": request.business_contact,
        "audience_type": request.audience_type,
        "audience_group_ids": request.audience_group_ids,
        "source_aliases": request.source_aliases,
        "status": "DRAFT",
        "updated_at": utc_now(),
        "updated_by": actor.user_id,
        "etag": new_etag(document.document_id, version.version_number + 1),
    }


async def build_updated_draft_records(
    *,
    ctx: PortalServiceContext,
    actor: PortalActor,
    document: KnowledgeDocumentRecord,
    version: KnowledgeVersionRecord,
    request: UpdateDraftRequest,
) -> tuple[KnowledgeVersionRecord, KnowledgeDocumentRecord]:
    asset_slug, assets_root = await ctx.validation_context(
        document_id=document.document_id,
        version_id=version.version_id,
        title=request.title,
        asset_slug=version.asset_slug,
    )
    validation = validate_draft(
        title=request.title,
        owner_unit_id=request.owner_unit_id,
        change_reason=request.change_reason,
        effective_at=request.effective_at,
        review_due_at=request.review_due_at,
        audience_type=request.audience_type,
        audience_group_ids=request.audience_group_ids,
        markdown_content=request.markdown_content,
        asset_slug=asset_slug,
        draft_assets_root=assets_root,
    )
    canonical = build_front_matter_markdown(
        title=request.title,
        owner_unit_id=request.owner_unit_id,
        effective_at=request.effective_at,
        review_due_at=request.review_due_at,
        audience_type=request.audience_type,
        audience_group_ids=request.audience_group_ids,
        version_number=version.version_number,
        body=request.markdown_content,
    )
    digest = content_hash(canonical)
    original_meta: dict[str, Any] = {}
    if getattr(request, "original_asset_token", None):
        store = OriginalAssetStore(ctx.settings)
        original_meta = store.commit_pending(
            request.original_asset_token,
            document_id=document.document_id,
            version_id=version.version_id,
            actor_id=actor.user_id,
        )
    updated_version = version.model_copy(
        update=draft_version_update_fields(
            request=request,
            version=version,
            canonical=canonical,
            digest=digest,
            validation=validation,
            original_meta=original_meta,
        )
    )
    updated_document = document.model_copy(
        update=draft_document_update_fields(
            request=request,
            document=document,
            version=version,
            actor=actor,
        )
    )
    return updated_version, updated_document


async def update_draft(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    document_id: str,
    request: UpdateDraftRequest,
    correlation_id: str,
) -> DocumentDetailResponse:
    document, version = await load_editable_draft(
        documents=documents,
        repository=ctx.repository,
        actor=actor,
        document_id=document_id,
        request=request,
    )
    updated_version, updated_document = await build_updated_draft_records(
        ctx=ctx,
        actor=actor,
        document=document,
        version=version,
        request=request,
    )
    await ctx.repository.save_version(updated_version)
    await ctx.repository.save_document(updated_document)
    await ctx.audit(
        actor=actor,
        action="document.update_draft",
        target_type="document",
        target_id=document_id,
        correlation_id=correlation_id,
        before={
            "status": document.status,
            "title": document.title,
            "category": document.category,
        },
        after={
            "status": updated_document.status,
            "title": updated_document.title,
            "category": updated_document.category,
        },
    )
    return await documents.get_document(actor, document_id)


async def validate_document(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    document_id: str,
) -> ValidationSummary:
    detail = await documents.get_document(actor, document_id)
    if detail.draft_version is None:
        raise ValueError("Document has no draft version to validate.")
    version = detail.draft_version
    asset_slug, assets_root = await ctx.validation_context(
        document_id=document_id,
        version_id=version.version_id,
        title=version.title,
        asset_slug=version.asset_slug,
    )
    validation = validate_draft(
        title=version.title,
        owner_unit_id=version.owner_unit_id,
        change_reason=version.change_reason,
        effective_at=version.effective_at,
        review_due_at=version.review_due_at,
        audience_type=version.audience_type,
        audience_group_ids=version.audience_group_ids,
        markdown_content=version.canonical_content,
        asset_slug=asset_slug,
        draft_assets_root=assets_root,
    )
    await ctx.repository.save_version(
        version.model_copy(update={"validation_summary": validation})
    )
    return validation


async def discard_draft(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    document_id: str,
    request: RemoveDocumentRequest,
    correlation_id: str,
) -> dict[str, str]:
    detail = await documents.get_document(actor, document_id)
    document = detail.document
    if document.status == "IN_REVIEW":
        raise ValueError("Documents in review cannot be removed. Approve or reject first.")
    ensure_can_remove_document(
        actor,
        document,
        relaxed_workflow=ctx.settings.effective_relaxed_workflow(),
    )
    if document.current_published_version_id and document.status == "PUBLISHED":
        raise ValueError("Published documents must be unpublished instead of discarded.")

    now = utc_now()
    if detail.draft_version is not None:
        await ctx.repository.save_version(
            detail.draft_version.model_copy(update={"status": "DISCARDED"})
        )
    updated_document = document.model_copy(
        update={
            "status": "DISCARDED",
            "draft_version_id": None,
            "updated_at": now,
            "updated_by": actor.user_id,
        }
    )
    await ctx.repository.save_document(updated_document)
    await ctx.audit(
        actor=actor,
        action="document.discard",
        target_type="document",
        target_id=document_id,
        correlation_id=correlation_id,
        reason=request.reason,
        before={"status": document.status},
        after={"status": "DISCARDED"},
    )
    return {"document_id": document_id, "status": "DISCARDED"}
