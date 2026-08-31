from __future__ import annotations

from pathlib import Path

from .models import (
    AssetRefSuggestion,
    CreateDocumentRequest,
    CreateTestCaseRequest,
    DashboardSummary,
    DocumentDetailResponse,
    DocumentListResponse,
    DraftAssetListResponse,
    ImportMarkdownResponse,
    PortalActor,
    PublishRequest,
    ReleaseRecord,
    RemoveDocumentRequest,
    ReviewDecisionRequest,
    RollbackRequest,
    SubmitReviewRequest,
    TestCaseRecord,
    TestRunRecord,
    UpdateDraftRequest,
    ValidationSummary,
)
from .rbac import ensure_can_view_audit
from .repository import PortalRepository
from .services.context import PortalServiceContext
from .services.dashboard_service import DashboardService
from .services.document_service import DocumentService
from .services.release_service import ReleaseService
from .services.review_service import ReviewService
from .settings import PortalSettings


class PortalService:
    """Thin application facade over domain services."""

    def __init__(self, settings: PortalSettings, repository: PortalRepository) -> None:
        ctx = PortalServiceContext(settings, repository)
        self._ctx = ctx
        self._documents = DocumentService(ctx)
        self._reviews = ReviewService(ctx, self._documents)
        self._releases = ReleaseService(ctx, self._documents)
        self._dashboard = DashboardService(ctx)

    async def dashboard(self, actor: PortalActor) -> DashboardSummary:
        return await self._dashboard.dashboard(actor)

    async def list_documents(
        self,
        actor: PortalActor,
        *,
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
    ) -> DocumentListResponse:
        return await self._documents.list_documents(
            actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
        )

    async def list_pending_reviews(self, actor: PortalActor):
        return await self._reviews.list_pending_reviews(actor)

    async def get_document(
        self, actor: PortalActor, document_id: str
    ) -> DocumentDetailResponse:
        return await self._documents.get_document(actor, document_id)

    async def create_document(
        self,
        actor: PortalActor,
        request: CreateDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        return await self._documents.create_document(actor, request, correlation_id)

    async def update_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: UpdateDraftRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        return await self._documents.update_draft(
            actor, document_id, request, correlation_id
        )

    async def validate_document(
        self, actor: PortalActor, document_id: str
    ) -> ValidationSummary:
        return await self._documents.validate_document(actor, document_id)

    async def submit_for_review(
        self,
        actor: PortalActor,
        document_id: str,
        request: SubmitReviewRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        return await self._reviews.submit_for_review(
            actor, document_id, request, correlation_id
        )

    async def decide_review(
        self,
        actor: PortalActor,
        review_id: str,
        request: ReviewDecisionRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        return await self._reviews.decide_review(
            actor, review_id, request, correlation_id
        )

    async def publish_version(
        self,
        actor: PortalActor,
        document_id: str,
        request: PublishRequest,
        correlation_id: str,
    ) -> ReleaseRecord:
        return await self._releases.publish_version(
            actor, document_id, request, correlation_id
        )

    async def discard_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> dict[str, str]:
        return await self._documents.discard_draft(
            actor, document_id, request, correlation_id
        )

    async def unpublish_document(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        return await self._releases.unpublish_document(
            actor, document_id, request, correlation_id
        )

    async def remove_document(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse | dict[str, str]:
        return await self._releases.remove_document(
            actor, document_id, request, correlation_id
        )

    async def rollback_release(
        self,
        actor: PortalActor,
        request: RollbackRequest,
        correlation_id: str,
    ) -> ReleaseRecord:
        return await self._releases.rollback_release(
            actor, request, correlation_id
        )

    async def list_releases(self, actor: PortalActor) -> list[ReleaseRecord]:
        return await self._releases.list_releases(actor)

    async def list_audit(self, actor: PortalActor, *, limit: int = 100):
        ensure_can_view_audit(actor)
        return await self._ctx.repository.list_audit_events(limit=limit)

    async def add_test_case(
        self,
        actor: PortalActor,
        document_id: str,
        request: CreateTestCaseRequest,
        correlation_id: str,
    ) -> TestCaseRecord:
        return await self._documents.add_test_case(
            actor, document_id, request, correlation_id
        )

    def import_markdown(self, raw: str) -> ImportMarkdownResponse:
        return self._documents.import_markdown(raw)

    async def list_draft_assets(
        self, actor: PortalActor, document_id: str
    ) -> DraftAssetListResponse:
        return await self._documents.list_draft_assets(actor, document_id)

    async def upload_draft_assets(
        self,
        actor: PortalActor,
        document_id: str,
        uploads: list[tuple[str, bytes]],
        correlation_id: str,
    ) -> DraftAssetListResponse:
        return await self._documents.upload_draft_assets(
            actor, document_id, uploads, correlation_id
        )

    async def delete_draft_asset(
        self,
        actor: PortalActor,
        document_id: str,
        filename: str,
        correlation_id: str,
    ) -> DraftAssetListResponse:
        return await self._documents.delete_draft_asset(
            actor, document_id, filename, correlation_id
        )

    async def suggest_asset_ref(
        self,
        actor: PortalActor,
        document_id: str,
        filename: str,
        alt_text: str = "",
    ) -> AssetRefSuggestion:
        return await self._documents.suggest_asset_ref(
            actor, document_id, filename, alt_text
        )

    def read_draft_asset(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
        filename: str,
    ) -> tuple[Path, str]:
        return self._documents.read_draft_asset(
            document_id, version_id, asset_slug, filename
        )

    async def start_revision(
        self,
        actor: PortalActor,
        document_id: str,
        correlation_id: str,
        change_reason: str = "Start a new revision from the published version.",
    ) -> DocumentDetailResponse:
        return await self._documents.start_revision(
            actor, document_id, correlation_id, change_reason
        )

    async def bootstrap_release_0001(
        self,
        actor: PortalActor,
        sources_dir: Path,
        correlation_id: str,
        release_id: str = "release-0001",
        bundled_index_path: Path | None = None,
    ) -> ReleaseRecord:
        return await self._ctx.migration.bootstrap_release_0001(
            actor=actor,
            sources_dir=sources_dir,
            correlation_id=correlation_id,
            release_id=release_id,
            bundled_index_path=bundled_index_path,
        )

    async def sync_from_local_corpus(
        self,
        actor: PortalActor,
        sources_dir: Path,
        correlation_id: str,
        bundled_index_path: Path | None = None,
        release_id: str = "release-0001",
    ) -> ReleaseRecord:
        return await self._ctx.migration.sync_from_local_corpus(
            actor=actor,
            sources_dir=sources_dir,
            bundled_index_path=bundled_index_path,
            correlation_id=correlation_id,
            release_id=release_id,
        )

    async def search_draft(
        self,
        actor: PortalActor,
        document_id: str,
        query: str,
        groups: list[str] | None = None,
        limit: int = 4,
    ):
        return await self._documents.search_draft(
            actor, document_id, query, groups, limit
        )

    async def run_test_case(
        self,
        actor: PortalActor,
        document_id: str,
        test_case_id: str,
        correlation_id: str,
    ) -> TestRunRecord:
        return await self._documents.run_test_case(
            actor, document_id, test_case_id, correlation_id
        )

    async def list_test_cases(
        self, actor: PortalActor, document_id: str
    ) -> list[TestCaseRecord]:
        return await self._documents.list_test_cases(actor, document_id)

    async def list_test_runs(
        self, actor: PortalActor, document_id: str
    ) -> list[TestRunRecord]:
        return await self._documents.list_test_runs(actor, document_id)
