"""Document service facade coordinating document queries, upload, and version services.

Refactored according to A08 to decouple upload/artifact, version, and review responsibilities.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_service.document_parsing import MarkdownLayoutParser
from agent_service.layout_chunking import (
    ChunkingProfile,
    chunk_parsed_document,
    chunk_quality_issues,
)
from knowledge_core.front_matter import parse_front_matter, strip_excluded_markdown

from ..draft_assets import DraftAssetStore, slug_from_title
from ..models import (
    AssetRefSuggestion,
    CreateDocumentRequest,
    CreateTestCaseRequest,
    DocumentDetailResponse,
    DocumentListResponse,
    DraftAssetListResponse,
    ImportMarkdownResponse,
    ImportPdfResponse,
    KnowledgeVersionRecord,
    PortalActor,
    ReleaseRecord,
    RemoveDocumentRequest,
    TestCaseRecord,
    TestRunRecord,
    UpdateDraftRequest,
    ValidationSummary,
)
from ..rbac import (
    ensure_document_visible,
    ensure_not_found,
)
from ..repository import PortalNotFoundError
from ..validation import validate_draft
from ..version_assets import (
    build_version_asset_context,
    images_for_chunk,
    read_version_asset,
)
from .context import PortalServiceContext
from .upload_service import UploadService
from .version_service import VersionService


class DocumentService:
    """Facade coordinating document reads, uploads, and versioning services."""

    def __init__(self, ctx: PortalServiceContext) -> None:
        self._ctx = ctx
        self._upload_service = UploadService(ctx, self)
        self._version_service = VersionService(ctx, self)

    @property
    def _repository(self):
        return self._ctx.repository

    @property
    def _settings(self):
        return self._ctx.settings

    async def list_documents(
        self,
        actor: PortalActor,
        *,
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
        format: str | None = None,
    ) -> DocumentListResponse:
        items = await self._repository.list_documents(
            actor=actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
            format=format,
        )
        return DocumentListResponse(items=items, total=len(items))

    async def get_document(self, actor: PortalActor, document_id: str) -> DocumentDetailResponse:
        document = await self._repository.get_document(document_id)
        ensure_not_found("document", document_id, document)
        ensure_document_visible(
            actor,
            document.owner_unit_id,
            document.created_by,
            tenant_id=document.tenant_id,
        )

        draft_version = None
        if document.draft_version_id:
            draft_version = await self._repository.get_version(document.draft_version_id)
        published_version = None
        if document.current_published_version_id:
            published_version = await self._repository.get_version(
                document.current_published_version_id
            )
        open_review = None
        if draft_version is not None:
            open_review = await self._repository.get_open_review_for_version(
                draft_version.version_id
            )
        draft_assets = None
        if draft_version is not None:
            store = DraftAssetStore(self._settings)
            slug = draft_version.asset_slug or slug_from_title(draft_version.title)
            draft_assets = DraftAssetListResponse(
                asset_slug=slug,
                items=store.list_assets(
                    document.document_id,
                    draft_version.version_id,
                    slug,
                ),
            )
            if any(
                issue.code == "ASSET_PATH_UNEXPECTED"
                for issue in draft_version.validation_summary.issues
            ):
                asset_slug, assets_root = await self._ctx.validation_context(
                    document_id=document.document_id,
                    version_id=draft_version.version_id,
                    title=draft_version.title,
                    asset_slug=draft_version.asset_slug,
                )
                refreshed = validate_draft(
                    title=draft_version.title,
                    owner_unit_id=draft_version.owner_unit_id,
                    change_reason=draft_version.change_reason,
                    effective_at=draft_version.effective_at,
                    review_due_at=draft_version.review_due_at,
                    audience_type=draft_version.audience_type,
                    audience_group_ids=draft_version.audience_group_ids,
                    markdown_content=draft_version.canonical_content,
                    asset_slug=asset_slug,
                    draft_assets_root=assets_root,
                )
                draft_version = draft_version.model_copy(update={"validation_summary": refreshed})
                await self._repository.save_version(draft_version)

        return self._ctx.document_detail_response(
            document=document,
            draft_version=draft_version,
            published_version=published_version,
            open_review=open_review,
            draft_assets=draft_assets,
            actor=actor,
        )

    async def preview_chunks(
        self,
        actor: PortalActor,
        document_id: str,
        *,
        profile: ChunkingProfile,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        detail = await self.get_document(actor, document_id)
        version = self._select_preview_version(detail, version_id)
        if version is None:
            if version_id is not None:
                raise PortalNotFoundError("version", version_id)
            raise ValueError("Document has no version available for chunk preview.")
        release = await self._active_release_for_version(version.version_id)
        asset_context = await build_version_asset_context(
            self._settings,
            version=version,
            release=release,
        )
        _, markdown_body = parse_front_matter(version.canonical_content)
        markdown_body = strip_excluded_markdown(markdown_body)
        parsed = MarkdownLayoutParser().parse(markdown_body, title=version.title)
        chunks, report = chunk_parsed_document(
            parsed,
            document_id=document_id,
            profile=profile,
        )
        quality_issues = chunk_quality_issues(report.profile, chunks)
        return {
            "documentId": document_id,
            "versionId": version.version_id,
            "releaseId": asset_context.release_id,
            "parser": {
                "name": parsed.parser_name,
                "version": parsed.parser_version,
            },
            "profile": report.profile.value,
            "quality": {
                "acceptable": report.is_acceptable,
                "coverageRatio": report.coverage_ratio,
                "sourceBlocks": report.source_blocks,
                "coveredBlocks": report.covered_blocks,
                "chunkCount": report.chunk_count,
                "shortChunkCount": report.short_chunk_count,
                "headingOnlyCount": report.heading_only_count,
                "orphanMediaCount": report.orphan_media_count,
                "duplicateChunkCount": report.duplicate_chunk_count,
            },
            "chunks": [
                {
                    "id": chunk.chunk_id,
                    "parentId": chunk.parent_id,
                    "neighborIds": list(chunk.neighbor_ids),
                    "title": chunk.title,
                    "content": chunk.content,
                    "contentPreview": chunk.content[:240],
                    "tokenCount": chunk.token_count,
                    "pageStart": chunk.page_start,
                    "pageEnd": chunk.page_end,
                    "headingPath": list(chunk.heading_path),
                    "contentHash": chunk.content_hash,
                    "parserVersion": chunk.parser_version,
                    "chunkerVersion": chunk.chunker_version,
                    "qualityIssues": list(quality_issues.get(chunk.chunk_id, ())),
                    "images": [
                        image.model_dump(mode="json")
                        for image in images_for_chunk(
                            chunk.content,
                            context=asset_context,
                        )
                    ],
                }
                for chunk in chunks
            ],
        }

    async def read_version_asset(
        self,
        actor: PortalActor,
        document_id: str,
        version_id: str,
        filename: str,
    ) -> tuple[bytes, str]:
        detail = await self.get_document(actor, document_id)
        version = self._select_preview_version(detail, version_id)
        if version is None:
            raise PortalNotFoundError("version", version_id)
        release = await self._active_release_for_version(version.version_id)
        context = await build_version_asset_context(
            self._settings,
            version=version,
            release=release,
        )
        return await read_version_asset(
            self._settings,
            context=context,
            filename=filename,
        )

    @staticmethod
    def _select_preview_version(
        detail: DocumentDetailResponse,
        version_id: str | None,
    ) -> KnowledgeVersionRecord | None:
        candidates = (detail.draft_version, detail.published_version)
        if version_id is None:
            return detail.draft_version or detail.published_version
        return next(
            (version for version in candidates if version and version.version_id == version_id),
            None,
        )

    async def _active_release_for_version(self, version_id: str) -> ReleaseRecord | None:
        active_release_id = await self._repository.get_active_release_id()
        if not active_release_id:
            return None
        release = await self._repository.get_release(active_release_id)
        if release is None:
            return None
        if any(entry.version_id == version_id for entry in release.manifest):
            return release
        return None

    # Delegation to VersionService
    async def create_document(
        self,
        actor: PortalActor,
        request: CreateDocumentRequest,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> DocumentDetailResponse:
        return await self._version_service.create_document(
            actor, request, correlation_id, idempotency_key=idempotency_key
        )

    async def update_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: UpdateDraftRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        return await self._version_service.update_draft(actor, document_id, request, correlation_id)

    async def validate_document(self, actor: PortalActor, document_id: str) -> ValidationSummary:
        return await self._version_service.validate_document(actor, document_id)

    async def discard_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> dict[str, str]:
        return await self._version_service.discard_draft(
            actor, document_id, request, correlation_id
        )

    async def start_revision(
        self,
        actor: PortalActor,
        document_id: str,
        correlation_id: str,
        change_reason: str = "Start a new revision from the published version.",
    ) -> DocumentDetailResponse:
        return await self._version_service.start_revision(
            actor, document_id, correlation_id, change_reason=change_reason
        )

    async def add_test_case(
        self,
        actor: PortalActor,
        document_id: str,
        request: CreateTestCaseRequest,
        correlation_id: str,
    ) -> TestCaseRecord:
        return await self._version_service.add_test_case(
            actor, document_id, request, correlation_id
        )

    async def search_draft(
        self,
        actor: PortalActor,
        document_id: str,
        query: str,
        groups: list[str] | None = None,
        limit: int = 4,
    ):
        return await self._version_service.search_draft(
            actor, document_id, query, groups=groups, limit=limit
        )

    async def run_test_case(
        self,
        actor: PortalActor,
        document_id: str,
        test_case_id: str,
        correlation_id: str,
    ) -> TestRunRecord:
        return await self._version_service.run_test_case(
            actor, document_id, test_case_id, correlation_id
        )

    async def list_test_cases(self, actor: PortalActor, document_id: str) -> list[TestCaseRecord]:
        return await self._version_service.list_test_cases(actor, document_id)

    async def list_test_runs(
        self,
        actor: PortalActor,
        document_id: str,
        test_case_id: str | None = None,
    ) -> list[TestRunRecord]:
        return await self._version_service.list_test_runs(
            actor, document_id, test_case_id=test_case_id
        )

    # Delegation to UploadService
    def import_markdown(
        self, actor: PortalActor, raw: str, *, filename: str | None = None
    ) -> ImportMarkdownResponse:
        return self._upload_service.import_markdown(actor, raw, filename=filename)

    def import_docx(
        self,
        actor: PortalActor,
        payload: bytes,
        *,
        filename: str | None = None,
    ) -> dict[str, object]:
        return self._upload_service.import_docx(actor, payload, filename=filename)

    def import_pdf(
        self,
        actor: PortalActor,
        payload: bytes,
        *,
        filename: str | None = None,
    ) -> ImportPdfResponse:
        return self._upload_service.import_pdf(actor, payload, filename=filename)

    async def import_pdf_smart(
        self,
        actor: PortalActor,
        payload: bytes,
        *,
        filename: str | None = None,
        async_mode: str | None = "auto",
        job_store: Any | None = None,
        background_tasks: Any | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ImportPdfResponse | dict[str, object]:
        return await self._upload_service.import_pdf_smart(
            actor,
            payload,
            filename=filename,
            async_mode=async_mode,
            job_store=job_store,
            background_tasks=background_tasks,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    async def list_draft_assets(
        self, actor: PortalActor, document_id: str
    ) -> DraftAssetListResponse:
        return await self._upload_service.list_draft_assets(actor, document_id)

    async def upload_draft_assets(
        self,
        actor: PortalActor,
        document_id: str,
        uploads: list[tuple[str, bytes]],
        correlation_id: str,
    ) -> DraftAssetListResponse:
        return await self._upload_service.upload_draft_assets(
            actor, document_id, uploads, correlation_id
        )

    async def delete_draft_asset(
        self,
        actor: PortalActor,
        document_id: str,
        filename: str,
        correlation_id: str,
    ) -> DraftAssetListResponse:
        return await self._upload_service.delete_draft_asset(
            actor, document_id, filename, correlation_id
        )

    async def suggest_asset_ref(
        self,
        actor: PortalActor,
        document_id: str,
        filename: str,
        alt_text: str = "",
    ) -> AssetRefSuggestion:
        return await self._upload_service.suggest_asset_ref(
            actor, document_id, filename, alt_text=alt_text
        )

    def read_draft_asset(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
        filename: str,
    ) -> tuple[Path, str]:
        return self._upload_service.read_draft_asset(document_id, version_id, asset_slug, filename)
