"""Document creation workflow for VersionService.

Extracted so create orchestration stays under architecture size limits while
preserving permission, idempotency, asset, and rollback behavior.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
from typing import Any, Protocol

from ..draft_assets import (
    DraftAssetStore,
    rewrite_local_image_refs,
    slug_from_title,
)
from ..models import (
    CreateDocumentRequest,
    DocumentDetailResponse,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    new_etag,
    utc_now,
)
from ..original_assets import OriginalAssetStore
from ..rbac import PortalPermissionError
from ..repository import new_id
from ..role_capabilities import ensure_can_create_document
from ..validation import (
    build_front_matter_markdown,
    build_parse_preview,
    content_hash,
    validate_draft,
)
from .context import PortalServiceContext


class DocumentLookup(Protocol):
    """Document facade method used after create."""

    async def get_document(
        self, actor: PortalActor, document_id: str
    ) -> DocumentDetailResponse: ...


def ensure_create_owner_access(actor: PortalActor, request: CreateDocumentRequest) -> None:
    ensure_can_create_document(actor)
    if (
        actor.role != "PLATFORM"
        and actor.owner_unit_ids
        and request.owner_unit_id not in actor.owner_unit_ids
    ):
        raise PortalPermissionError(
            "You do not have permission to create documents for this owner unit."
        )


async def resolve_create_idempotency(
    ctx: PortalServiceContext,
    *,
    actor: PortalActor,
    request: CreateDocumentRequest,
    idempotency_key: str | None,
) -> tuple[str | None, str | None, DocumentDetailResponse | None]:
    if not idempotency_key:
        return None, None, None
    scope_key = f"create_doc::{actor.tenant_id or 'default'}::{actor.user_id}::{idempotency_key}"
    payload_hash = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
    status, cached = await ctx.claim_idempotency(scope_key, payload_hash)
    if status == "CACHED" and cached is not None:
        if isinstance(cached, dict):
            return scope_key, payload_hash, DocumentDetailResponse.model_validate(cached)
        return scope_key, payload_hash, cached
    return scope_key, payload_hash, None


def write_inline_create_assets(
    *,
    settings: Any,
    document_id: str,
    version_id: str,
    asset_slug: str,
    request: CreateDocumentRequest,
) -> tuple[str, bool]:
    markdown_content = request.markdown_content
    if not request.assets:
        return markdown_content, False
    store = DraftAssetStore(settings)
    for asset in request.assets:
        try:
            payload = base64.b64decode(asset.content_base64, validate=False)
        except Exception as exc:
            raise ValueError(f"Invalid base64 for asset {asset.filename}.") from exc
        store.save_asset(
            document_id=document_id,
            version_id=version_id,
            asset_slug=asset_slug,
            filename=asset.filename,
            payload=payload,
        )
    rewritten = rewrite_local_image_refs(markdown_content, asset_slug=asset_slug)
    return rewritten, True


def commit_create_original_asset(
    *,
    original_store: OriginalAssetStore,
    request: CreateDocumentRequest,
    document_id: str,
    version_id: str,
    actor_id: str,
) -> tuple[dict[str, Any], bool]:
    if not request.original_asset_token:
        return {}, False
    if request.source_type not in {"PDF", "DOCX"}:
        raise ValueError("Original asset token is only valid for PDF or DOCX documents.")
    metadata = original_store.commit_pending(
        request.original_asset_token,
        document_id=document_id,
        version_id=version_id,
        actor_id=actor_id,
    )
    return metadata, True


def build_create_records(
    *,
    actor: PortalActor,
    request: CreateDocumentRequest,
    document_id: str,
    version_id: str,
    asset_slug: str,
    markdown_content: str,
    validation: Any,
    original_metadata: dict[str, Any],
) -> tuple[KnowledgeVersionRecord, KnowledgeDocumentRecord]:
    now = utc_now()
    canonical = build_front_matter_markdown(
        title=request.title,
        owner_unit_id=request.owner_unit_id,
        effective_at=request.effective_at,
        review_due_at=request.review_due_at,
        audience_type=request.audience_type,
        audience_group_ids=request.audience_group_ids,
        version_number=1,
        body=markdown_content,
    )
    digest = content_hash(canonical)
    version = KnowledgeVersionRecord(
        version_id=version_id,
        document_id=document_id,
        version_number=1,
        source_type=request.source_type,
        content_hash=digest,
        canonical_content=canonical,
        change_summary=request.change_summary,
        change_reason=request.change_reason,
        effective_at=request.effective_at,
        review_due_at=request.review_due_at,
        audience_type=request.audience_type,
        audience_group_ids=request.audience_group_ids,
        source_aliases=request.source_aliases,
        content_state=request.content_state,
        expires_at=request.expires_at,
        applicable_environments=request.applicable_environments,
        owner_unit_id=request.owner_unit_id,
        business_contact=request.business_contact,
        category=request.category,
        summary=request.summary,
        title=request.title,
        asset_slug=asset_slug,
        validation_summary=validation,
        parse_preview=build_parse_preview(canonical, request.title),
        **original_metadata,
        etag=new_etag(digest),
        created_at=now,
        created_by=actor.user_id,
    )
    document = KnowledgeDocumentRecord(
        document_id=document_id,
        title=request.title,
        summary=request.summary,
        category=request.category,
        owner_unit_id=request.owner_unit_id,
        business_contact=request.business_contact,
        audience_type=request.audience_type,
        audience_group_ids=request.audience_group_ids,
        source_aliases=request.source_aliases,
        draft_version_id=version_id,
        status="DRAFT",
        etag=new_etag(document_id, 1),
        created_at=now,
        created_by=actor.user_id,
        updated_at=now,
        updated_by=actor.user_id,
        tenant_id=actor.tenant_id,
    )
    return version, document


def cleanup_failed_create(
    *,
    settings: Any,
    original_store: OriginalAssetStore,
    document_id: str,
    version_id: str,
    assets_written: bool,
    original_asset_committed: bool,
) -> None:
    if assets_written:
        shutil.rmtree(
            DraftAssetStore(settings).bundle_dir(document_id, version_id),
            ignore_errors=True,
        )
    if original_asset_committed:
        original_store.remove_version(document_id=document_id, version_id=version_id)


async def prepare_create_payload(
    *,
    ctx: PortalServiceContext,
    actor: PortalActor,
    request: CreateDocumentRequest,
    document_id: str,
    version_id: str,
    original_store: OriginalAssetStore,
) -> tuple[KnowledgeVersionRecord, KnowledgeDocumentRecord, bool, bool]:
    asset_slug = slug_from_title(request.title)
    _, assets_root = await ctx.validation_context(
        document_id=document_id,
        version_id=version_id,
        title=request.title,
        asset_slug=asset_slug,
    )
    markdown_content, assets_written = write_inline_create_assets(
        settings=ctx.settings,
        document_id=document_id,
        version_id=version_id,
        asset_slug=asset_slug,
        request=request,
    )
    validation = validate_draft(
        title=request.title,
        owner_unit_id=request.owner_unit_id,
        change_reason=request.change_reason,
        effective_at=request.effective_at,
        review_due_at=request.review_due_at,
        audience_type=request.audience_type,
        audience_group_ids=request.audience_group_ids,
        markdown_content=markdown_content,
        asset_slug=asset_slug,
        draft_assets_root=assets_root,
    )
    if validation.has_blocking:
        raise ValueError(validation)
    original_metadata, original_asset_committed = commit_create_original_asset(
        original_store=original_store,
        request=request,
        document_id=document_id,
        version_id=version_id,
        actor_id=actor.user_id,
    )
    version, document = build_create_records(
        actor=actor,
        request=request,
        document_id=document_id,
        version_id=version_id,
        asset_slug=asset_slug,
        markdown_content=markdown_content,
        validation=validation,
        original_metadata=original_metadata,
    )
    return version, document, assets_written, original_asset_committed


async def create_document(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    request: CreateDocumentRequest,
    correlation_id: str,
    idempotency_key: str | None = None,
) -> DocumentDetailResponse:
    ensure_create_owner_access(actor, request)
    scope_key, payload_hash, cached = await resolve_create_idempotency(
        ctx, actor=actor, request=request, idempotency_key=idempotency_key
    )
    if cached is not None:
        return cached

    assets_written = False
    original_asset_committed = False
    original_store = OriginalAssetStore(ctx.settings)
    document_id = new_id("doc")
    version_id = new_id("ver")
    try:
        version, document, assets_written, original_asset_committed = await prepare_create_payload(
            ctx=ctx,
            actor=actor,
            request=request,
            document_id=document_id,
            version_id=version_id,
            original_store=original_store,
        )
        await ctx.repository.save_version(version)
        await ctx.repository.save_document(document)
        await ctx.audit(
            actor=actor,
            action="document.create",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
            before=None,
            after={"status": document.status, "title": document.title},
        )
        response = await documents.get_document(actor, document_id)
        if scope_key and payload_hash:
            await ctx.complete_idempotency(scope_key, payload_hash, response)
        return response
    except Exception:
        cleanup_failed_create(
            settings=ctx.settings,
            original_store=original_store,
            document_id=document_id,
            version_id=version_id,
            assets_written=assets_written,
            original_asset_committed=original_asset_committed,
        )
        raise
