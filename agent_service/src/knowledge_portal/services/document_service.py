"""Document service facade coordinating document queries, upload, and version services.

Refactored according to A08 to decouple upload/artifact, version, and review responsibilities.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    TestCaseRecord,
    TestRunRecord,
    UpdateDraftRequest,
    ValidationSummary,
)
from ..rbac import (
    ensure_document_visible,
    ensure_not_found,
)
from ..validation import validate_draft
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

    async def get_document(
        self, actor: PortalActor, document_id: str
    ) -> DocumentDetailResponse:
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
                asset_slug, assets_root = self._ctx.validation_context(
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
                draft_version = draft_version.model_copy(
                    update={"validation_summary": refreshed}
                )
                await self._repository.save_version(draft_version)

        return self._ctx.document_detail_response(
            document=document,
            draft_version=draft_version,
            published_version=published_version,
            open_review=open_review,
            draft_assets=draft_assets,
            actor=actor,
        )

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
        return await self._version_service.update_draft(
            actor, document_id, request, correlation_id
        )

    async def validate_document(
        self, actor: PortalActor, document_id: str
    ) -> ValidationSummary:
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

    async def list_test_cases(
        self, actor: PortalActor, document_id: str
    ) -> list[TestCaseRecord]:
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
    ) -> ImportPdfResponse | dict[str, object]:
        return await self._upload_service.import_pdf_smart(
            actor,
            payload,
            filename=filename,
            async_mode=async_mode,
            job_store=job_store,
            background_tasks=background_tasks,
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
        return self._upload_service.read_draft_asset(
            document_id, version_id, asset_slug, filename
        )
