from __future__ import annotations

from pathlib import Path

from ..draft_assets import (
    DraftAssetStore,
    asset_content_type,
    markdown_asset_ref,
    parse_markdown_import,
    slug_from_title,
)
from ..draft_retrieval import evaluate_test_case, search_draft_version
from ..models import (
    AssetRefSuggestion,
    CreateDocumentRequest,
    CreateTestCaseRequest,
    DocumentDetailResponse,
    DocumentListResponse,
    DraftAssetListResponse,
    ImportMarkdownResponse,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    RemoveDocumentRequest,
    TestCaseRecord,
    TestRunRecord,
    UpdateDraftRequest,
    ValidationSummary,
    new_etag,
    utc_now,
)
from ..rbac import ensure_can_edit, ensure_can_remove_document, ensure_document_visible, ensure_not_found
from ..repository import PortalNotFoundError, VersionConflictError, new_id
from ..validation import (
    build_front_matter_markdown,
    build_parse_preview,
    content_hash,
    validate_draft,
)
from .context import PortalServiceContext


class DocumentService:
    def __init__(self, ctx: PortalServiceContext) -> None:
        self._ctx = ctx

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
    ) -> DocumentListResponse:
        items = await self._repository.list_documents(
            actor=actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
        )
        return DocumentListResponse(items=items, total=len(items))

    async def get_document(self, actor: PortalActor, document_id: str) -> DocumentDetailResponse:
        document = await self._repository.get_document(document_id)
        ensure_not_found("document", document_id, document)
        ensure_document_visible(actor, document.owner_unit_id, document.created_by)

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
        return self._ctx.document_detail_response(
            document=document,
            draft_version=draft_version,
            published_version=published_version,
            open_review=open_review,
            draft_assets=draft_assets,
            actor=actor,
        )


    async def create_document(
        self,
        actor: PortalActor,
        request: CreateDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        document_id = new_id("doc")
        version_id = new_id("ver")
        asset_slug = slug_from_title(request.title)
        _, assets_root = self._ctx.validation_context(
            document_id=document_id,
            version_id=version_id,
            title=request.title,
            asset_slug=asset_slug,
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
        if validation.has_blocking:
            raise ValueError(validation)

        now = utc_now()
        canonical = build_front_matter_markdown(
            title=request.title,
            owner_unit_id=request.owner_unit_id,
            effective_at=request.effective_at,
            review_due_at=request.review_due_at,
            audience_type=request.audience_type,
            audience_group_ids=request.audience_group_ids,
            version_number=1,
            body=request.markdown_content,
        )
        digest = content_hash(canonical)
        version = KnowledgeVersionRecord(
            version_id=version_id,
            document_id=document_id,
            version_number=1,
            content_hash=digest,
            canonical_content=canonical,
            change_summary=request.change_summary,
            change_reason=request.change_reason,
            effective_at=request.effective_at,
            review_due_at=request.review_due_at,
            audience_type=request.audience_type,
            audience_group_ids=request.audience_group_ids,
            owner_unit_id=request.owner_unit_id,
            business_contact=request.business_contact,
            category=request.category,
            summary=request.summary,
            title=request.title,
            asset_slug=asset_slug,
            validation_summary=validation,
            parse_preview=build_parse_preview(canonical, request.title),
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
            draft_version_id=version_id,
            status="DRAFT",
            etag=new_etag(document_id, 1),
            created_at=now,
            created_by=actor.user_id,
            updated_at=now,
            updated_by=actor.user_id,
        )
        await self._repository.save_version(version)
        await self._repository.save_document(document)
        await self._ctx.audit(
            actor=actor,
            action="document.create",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
        )
        return await self.get_document(actor, document_id)

    async def update_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: UpdateDraftRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        detail = await self.get_document(actor, document_id)
        document = detail.document
        ensure_can_edit(actor, document.owner_unit_id, document.created_by)
        if document.status not in {"DRAFT", "CHANGES_REQUESTED", "APPROVED"}:
            raise ValueError("Only draft documents can be edited.")
        if document.etag != request.etag:
            raise VersionConflictError(document_id)
        if not document.draft_version_id:
            raise ValueError("Document has no editable draft version.")

        version = await self._repository.get_version(document.draft_version_id)
        ensure_not_found("version", document.draft_version_id, version)
        if version.status not in {"DRAFT", "CHANGES_REQUESTED", "APPROVED"}:
            raise ValueError("Draft version is locked for editing.")

        asset_slug, assets_root = self._ctx.validation_context(
            document_id=document_id,
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
        updated_version = version.model_copy(
            update={
                "title": request.title,
                "summary": request.summary,
                "category": request.category,
                "owner_unit_id": request.owner_unit_id,
                "business_contact": request.business_contact,
                "audience_type": request.audience_type,
                "audience_group_ids": request.audience_group_ids,
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
            }
        )
        updated_document = document.model_copy(
            update={
                "title": request.title,
                "summary": request.summary,
                "category": request.category,
                "owner_unit_id": request.owner_unit_id,
                "business_contact": request.business_contact,
                "audience_type": request.audience_type,
                "audience_group_ids": request.audience_group_ids,
                "status": "DRAFT",
                "updated_at": utc_now(),
                "updated_by": actor.user_id,
                "etag": new_etag(document.document_id, version.version_number + 1),
            }
        )
        await self._repository.save_version(updated_version)
        await self._repository.save_document(updated_document)
        await self._ctx.audit(
            actor=actor,
            action="document.update_draft",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
        )
        return await self.get_document(actor, document_id)

    async def validate_document(
        self, actor: PortalActor, document_id: str
    ) -> ValidationSummary:
        detail = await self.get_document(actor, document_id)
        if detail.draft_version is None:
            raise ValueError("Document has no draft version to validate.")
        version = detail.draft_version
        asset_slug, assets_root = self._ctx.validation_context(
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
        await self._repository.save_version(
            version.model_copy(update={"validation_summary": validation})
        )
        return validation

    async def discard_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> dict[str, str]:
        detail = await self.get_document(actor, document_id)
        document = detail.document
        if document.status == "IN_REVIEW":
            raise ValueError(
                "Documents in review cannot be removed. Approve or reject first."
            )
        ensure_can_remove_document(
            actor,
            document,
            relaxed_workflow=self._settings.effective_relaxed_workflow(),
        )
        if document.current_published_version_id and document.status == "PUBLISHED":
            raise ValueError(
                "Published documents must be unpublished instead of discarded."
            )

        now = utc_now()
        if detail.draft_version is not None:
            await self._repository.save_version(
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
        await self._repository.save_document(updated_document)
        await self._ctx.audit(
            actor=actor,
            action="document.discard",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
            reason=request.reason,
        )
        return {"document_id": document_id, "status": "DISCARDED"}

    async def add_test_case(
        self,
        actor: PortalActor,
        document_id: str,
        request: CreateTestCaseRequest,
        correlation_id: str,
    ) -> TestCaseRecord:
        detail = await self.get_document(actor, document_id)
        if detail.draft_version is None:
            raise ValueError("Draft version is required.")
        test_case = TestCaseRecord(
            test_case_id=new_id("test"),
            version_id=detail.draft_version.version_id,
            question=request.question,
            expected_document_id=document_id,
            simulated_audience=request.simulated_audience,
            notes=request.notes,
        )
        await self._repository.save_test_case(test_case)
        await self._ctx.audit(
            actor=actor,
            action="test_case.create",
            target_type="test_case",
            target_id=test_case.test_case_id,
            correlation_id=correlation_id,
        )
        return test_case

    def import_markdown(self, raw: str, *, filename: str | None = None) -> ImportMarkdownResponse:
        parsed = parse_markdown_import(
            raw,
            default_owner_unit_id=self._settings.default_owner_unit_id,
            filename=filename,
        )
        warnings: list[str] = []
        if raw.lstrip().startswith("---"):
            warnings.append("Front matter was parsed into metadata fields.")
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

    async def _require_editable_draft(
        self, actor: PortalActor, document_id: str
    ) -> tuple[KnowledgeDocumentRecord, KnowledgeVersionRecord]:
        detail = await self.get_document(actor, document_id)
        document = detail.document
        ensure_can_edit(actor, document.owner_unit_id, document.created_by)
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
        document, version = await self._require_editable_draft(actor, document_id)
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
            raise PortalNotFoundError(f"Draft asset not found: {filename}")
        return target, asset_content_type(target.suffix)

    async def start_revision(
        self,
        actor: PortalActor,
        document_id: str,
        correlation_id: str,
        change_reason: str = "Start a new revision from the published version.",
    ) -> DocumentDetailResponse:
        detail = await self.get_document(actor, document_id)
        document = detail.document
        ensure_can_edit(actor, document.owner_unit_id, document.created_by)
        if document.status != "PUBLISHED" or detail.published_version is None:
            raise ValueError("Only published documents can start a new revision.")
        if document.draft_version_id is not None:
            raise ValueError("Document already has an open draft.")

        published = detail.published_version
        now = utc_now()
        version_id = new_id("ver")
        asset_slug = published.asset_slug or slug_from_title(published.title)
        store = DraftAssetStore(self._settings)
        store.copy_bundle(
            source_document_id=document_id,
            source_version_id=published.version_id,
            target_document_id=document_id,
            target_version_id=version_id,
            asset_slug=asset_slug,
        )
        version = KnowledgeVersionRecord(
            version_id=version_id,
            document_id=document_id,
            version_number=published.version_number + 1,
            source_type="MARKDOWN_UPLOAD",
            content_hash=published.content_hash,
            canonical_content=published.canonical_content,
            change_summary=f"Revision {published.version_number + 1}",
            change_reason=change_reason,
            effective_at=published.effective_at,
            review_due_at=published.review_due_at,
            audience_type=published.audience_type,
            audience_group_ids=published.audience_group_ids,
            owner_unit_id=published.owner_unit_id,
            business_contact=published.business_contact,
            category=published.category,
            summary=published.summary,
            title=published.title,
            asset_slug=asset_slug,
            status="DRAFT",
            validation_summary=ValidationSummary(issues=[]),
            parse_preview=published.parse_preview,
            etag=new_etag(published.content_hash, published.version_number + 1),
            created_at=now,
            created_by=actor.user_id,
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
        await self._repository.save_version(version)
        await self._repository.save_document(updated_document)
        await self._ctx.audit(
            actor=actor,
            action="document.start_revision",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
        )
        return await self.get_document(actor, document_id)

    async def search_draft(
        self,
        actor: PortalActor,
        document_id: str,
        query: str,
        groups: list[str] | None = None,
        limit: int = 4,
    ):
        detail = await self.get_document(actor, document_id)
        if detail.draft_version is None:
            raise ValueError("Draft version is required.")
        return search_draft_version(
            version=detail.draft_version,
            query=query,
            groups=groups or [],
            settings=self._settings,
            limit=limit,
        )

    async def run_test_case(
        self,
        actor: PortalActor,
        document_id: str,
        test_case_id: str,
        correlation_id: str,
    ) -> TestRunRecord:
        detail = await self.get_document(actor, document_id)
        if detail.draft_version is None:
            raise ValueError("Draft version is required.")
        cases = await self._repository.list_test_cases(detail.draft_version.version_id)
        test_case = next((item for item in cases if item.test_case_id == test_case_id), None)
        ensure_not_found("test_case", test_case_id, test_case)

        status, answer_excerpt, cited_titles, failure_reason = evaluate_test_case(
            version=detail.draft_version,
            question=test_case.question,
            simulated_audience=test_case.simulated_audience,
            settings=self._settings,
        )
        test_run = TestRunRecord(
            test_run_id=new_id("run"),
            test_case_id=test_case_id,
            version_id=detail.draft_version.version_id,
            status=status,
            answer_excerpt=answer_excerpt,
            cited_titles=cited_titles,
            failure_reason=failure_reason,
            executed_at=utc_now(),
            executed_by=actor.user_id,
        )
        await self._repository.save_test_run(test_run)
        await self._ctx.audit(
            actor=actor,
            action="test_case.run",
            target_type="test_case",
            target_id=test_case_id,
            correlation_id=correlation_id,
            metadata={"status": status},
        )
        return test_run

    async def list_test_cases(
        self, actor: PortalActor, document_id: str
    ) -> list[TestCaseRecord]:
        detail = await self.get_document(actor, document_id)
        if detail.draft_version is None:
            return []
        return await self._repository.list_test_cases(detail.draft_version.version_id)

    async def list_test_runs(
        self, actor: PortalActor, document_id: str
    ) -> list[TestRunRecord]:
        detail = await self.get_document(actor, document_id)
        if detail.draft_version is None:
            return []
        return await self._repository.list_test_runs(detail.draft_version.version_id)

