"""Upload, import, and draft asset management service.

Handles raw file ingestion, PDF/Markdown parsing, draft assets, and raw bytes preservation (A08).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..draft_assets import (
    DraftAssetStore,
    asset_content_type,
    markdown_asset_ref,
    parse_markdown_import,
    slug_from_title,
)
from ..models import (
    AssetRefSuggestion,
    DraftAssetListResponse,
    ImportMarkdownResponse,
    ImportPdfResponse,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    utc_now,
)
from ..original_assets import OriginalAssetStore
from ..pdf_text import extract_text_pdf, pdf_text_to_markdown
from ..rbac import ensure_can_edit
from ..repository import PortalNotFoundError
from ..role_capabilities import ensure_can_import_markdown
from .context import PortalServiceContext


class UploadService:
    """Service handling document uploads, imports, and draft asset lifecycle."""

    def __init__(self, ctx: PortalServiceContext, document_service: Any = None) -> None:
        self._ctx = ctx
        self._document_service = document_service

    @property
    def _repository(self):
        return self._ctx.repository

    @property
    def _settings(self):
        return self._ctx.settings

    def import_markdown(
        self, actor: PortalActor, raw: str, *, filename: str | None = None
    ) -> ImportMarkdownResponse:
        ensure_can_import_markdown(actor)
        parsed = parse_markdown_import(
            raw,
            default_owner_unit_id=self._settings.default_owner_unit_id,
            filename=filename,
        )
        warnings: list[str] = []
        if raw.lstrip().startswith("---"):
            warnings.append("已解析文件開頭的 metadata 欄位。")
        return ImportMarkdownResponse(
            title=str(parsed["title"]),
            owner_unit_id=str(parsed["owner_unit_id"]),
            effective_at=str(parsed["effective_at"]),
            review_due_at=str(parsed["review_due_at"]),
            audience_type=parsed["audience_type"],  # type: ignore[arg-type]
            audience_group_ids=list(parsed["audience_group_ids"]),  # type: ignore[arg-type]
            markdown_content=str(parsed["markdown_content"]),
            asset_slug=str(parsed["asset_slug"]),
            warnings=warnings,
        )

    def import_pdf(
        self,
        actor: PortalActor,
        payload: bytes,
        *,
        filename: str | None = None,
    ) -> ImportPdfResponse:
        ensure_can_import_markdown(actor)
        original_metadata = OriginalAssetStore(self._settings).store_pending(
            payload,
            filename=filename,
            actor_id=actor.user_id,
        )
        original_store = OriginalAssetStore(self._settings)
        try:
            text, page_count = extract_text_pdf(payload)
        except Exception:
            original_store.discard_pending(original_metadata.get("original_asset_token"))
            raise
        stem = Path(filename or "document.pdf").stem.strip() or "PDF Document"
        markdown_content = pdf_text_to_markdown(text, stem)
        today = utc_now().date().isoformat()
        return ImportPdfResponse(
            title=stem,
            owner_unit_id=self._settings.default_owner_unit_id,
            effective_at=today,
            review_due_at=today,
            audience_type="ALL_EMPLOYEES",
            audience_group_ids=[],
            markdown_content=markdown_content,
            asset_slug=slug_from_title(stem),
            page_count=page_count,
            warnings=["已從文字型 PDF 擷取內容並轉為 Markdown 草稿。"],
            conversion_mode="legacy",
            conversion_engine="legacy_text",
            assets=[],
            **original_metadata,
            mode="sync",
        )

    async def import_pdf_smart(
        self,
        actor: PortalActor,
        payload: bytes,
        *,
        filename: str | None = None,
        async_mode: str | None = "auto",
        job_store: Any | None = None,
        background_tasks: Any | None = None,
    ) -> ImportPdfResponse | dict[str, object]:
        """Import PDF via converter service when configured; else legacy text extract."""
        from ..pdf_convert_jobs import (
            conversion_to_import_dict,
            convert_pdf_bytes,
            should_convert_async,
        )
        from ..pdf_text import count_pdf_pages

        ensure_can_import_markdown(actor)
        safe_name = filename or "document.pdf"
        original_metadata = OriginalAssetStore(self._settings).store_pending(
            payload,
            filename=safe_name,
            actor_id=actor.user_id,
        )
        try:
            page_count = count_pdf_pages(payload)
        except Exception:
            page_count = None
        if should_convert_async(
            self._settings,
            byte_size=len(payload),
            page_count=page_count,
            force=async_mode,
        ):
            if job_store is None:
                raise ValueError("Async PDF conversion requires a job store.")
            job = job_store.create_job(
                payload=payload,
                filename=safe_name,
                actor_id=actor.user_id,
                page_count=page_count,
                original_asset=original_metadata,
            )
            job_store.schedule(job.job_id, background_tasks)
            return {
                "mode": "async",
                "jobId": job.job_id,
                "status": job.status,
                "filename": job.filename,
                "pageCount": job.page_count,
                "byteSize": job.byte_size,
                "message": "PDF conversion queued. Poll /api/documents/pdf-jobs/{jobId}.",
            }
        try:
            result = await convert_pdf_bytes(self._settings, payload, filename=safe_name)
            data = conversion_to_import_dict(
                result,
                filename=safe_name,
                owner_unit_id=self._settings.default_owner_unit_id,
                original_asset=original_metadata,
            )
        except Exception:
            OriginalAssetStore(self._settings).discard_pending(
                original_metadata.get("original_asset_token")
            )
            raise
        return ImportPdfResponse(**data)

    async def _require_editable_draft(
        self, actor: PortalActor, document_id: str
    ) -> tuple[KnowledgeDocumentRecord, KnowledgeVersionRecord]:
        detail = await self._document_service.get_document(actor, document_id)
        document = detail.document
        ensure_can_edit(
            actor,
            document.owner_unit_id,
            document.created_by,
            tenant_id=document.tenant_id,
        )
        if detail.draft_version is None:
            raise ValueError("Document has no editable draft version.")
        if document.status not in {"DRAFT", "CHANGES_REQUESTED"}:
            raise ValueError("Document cannot be edited in its current state.")
        return document, detail.draft_version

    async def list_draft_assets(
        self, actor: PortalActor, document_id: str
    ) -> DraftAssetListResponse:
        _, version = await self._require_editable_draft(actor, document_id)
        store = DraftAssetStore(self._settings)
        slug = version.asset_slug or slug_from_title(version.title)
        return DraftAssetListResponse(
            asset_slug=slug,
            items=store.list_assets(document_id, version.version_id, slug),
        )

    async def upload_draft_assets(
        self,
        actor: PortalActor,
        document_id: str,
        uploads: list[tuple[str, bytes]],
        correlation_id: str,
    ) -> DraftAssetListResponse:
        _document, version = await self._require_editable_draft(actor, document_id)
        store = DraftAssetStore(self._settings)
        slug = version.asset_slug or slug_from_title(version.title)
        if not version.asset_slug:
            version = version.model_copy(update={"asset_slug": slug})
            await self._repository.save_version(version)
        for filename, payload in uploads:
            store.save_asset(
                document_id=document_id,
                version_id=version.version_id,
                asset_slug=slug,
                filename=filename,
                payload=payload,
            )
        await self._ctx.audit(
            actor=actor,
            action="draft_asset.upload",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
            metadata={"count": len(uploads)},
        )
        return await self.list_draft_assets(actor, document_id)

    async def delete_draft_asset(
        self,
        actor: PortalActor,
        document_id: str,
        filename: str,
        correlation_id: str,
    ) -> DraftAssetListResponse:
        _, version = await self._require_editable_draft(actor, document_id)
        store = DraftAssetStore(self._settings)
        slug = version.asset_slug or slug_from_title(version.title)
        store.delete_asset(
            document_id=document_id,
            version_id=version.version_id,
            asset_slug=slug,
            filename=filename,
        )
        await self._ctx.audit(
            actor=actor,
            action="draft_asset.delete",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
            metadata={"filename": filename},
        )
        return await self.list_draft_assets(actor, document_id)

    async def suggest_asset_ref(
        self,
        actor: PortalActor,
        document_id: str,
        filename: str,
        alt_text: str = "",
    ) -> AssetRefSuggestion:
        _, version = await self._require_editable_draft(actor, document_id)
        slug = version.asset_slug or slug_from_title(version.title)
        normalized = filename or DraftAssetStore(self._settings).next_filename(
            document_id,
            version.version_id,
            slug,
        )
        return AssetRefSuggestion(
            asset_slug=slug,
            filename=normalized,
            markdown=markdown_asset_ref(
                asset_slug=slug,
                filename=normalized,
                alt_text=alt_text,
            ),
        )

    def read_draft_asset(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
        filename: str,
    ) -> tuple[Path, str]:
        store = DraftAssetStore(self._settings)
        target = store.asset_dir(document_id, version_id, asset_slug) / filename
        if not target.is_file():
            raise PortalNotFoundError("draft asset", filename)
        return target, asset_content_type(target.suffix)
