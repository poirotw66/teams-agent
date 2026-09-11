"""Version and draft lifecycle service.

Handles draft creation, validation, revisions, and draft test cases (A08).
"""

from __future__ import annotations

import base64
import hashlib
import shutil
from typing import Any

from ..draft_assets import (
    DraftAssetStore,
    rewrite_local_image_refs,
    slug_from_title,
)
from ..draft_retrieval import evaluate_test_case, search_draft_version
from ..models import (
    CreateDocumentRequest,
    CreateTestCaseRequest,
    DocumentDetailResponse,
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
from ..original_assets import OriginalAssetStore
from ..rbac import (
    PortalPermissionError,
    ensure_can_edit,
    ensure_can_remove_document,
    ensure_not_found,
)
from ..repository import VersionConflictError, new_id
from ..role_capabilities import ensure_can_create_document
from ..validation import (
    build_front_matter_markdown,
    build_parse_preview,
    content_hash,
    validate_draft,
)
from .context import PortalServiceContext


class VersionService:
    """Service handling draft creation, revisions, and test cases."""

    def __init__(self, ctx: PortalServiceContext, document_service: Any = None) -> None:
        self._ctx = ctx
        self._document_service = document_service

    @property
    def _repository(self):
        return self._ctx.repository

    @property
    def _settings(self):
        return self._ctx.settings

    async def create_document(
        self,
        actor: PortalActor,
        request: CreateDocumentRequest,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> DocumentDetailResponse:
        ensure_can_create_document(actor)
        if (
            actor.role != "PLATFORM"
            and actor.owner_unit_ids
            and request.owner_unit_id not in actor.owner_unit_ids
        ):
            raise PortalPermissionError(
                "You do not have permission to create documents for this owner unit."
            )

        if idempotency_key:
            scope_key = f"create_doc::{actor.tenant_id or 'default'}::{actor.user_id}::{idempotency_key}"
            payload_hash = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
            status, cached = await self._ctx.claim_idempotency(scope_key, payload_hash)
            if status == "CACHED" and cached is not None:
                if isinstance(cached, dict):
                    return DocumentDetailResponse.model_validate(cached)
                return cached

        assets_written = False
        original_asset_committed = False
        original_store = OriginalAssetStore(self._settings)
        try:
            document_id = new_id("doc")
            version_id = new_id("ver")
            asset_slug = slug_from_title(request.title)
            _, assets_root = self._ctx.validation_context(
                document_id=document_id,
                version_id=version_id,
                title=request.title,
                asset_slug=asset_slug,
            )
            markdown_content = request.markdown_content
            if request.assets:
                store = DraftAssetStore(self._settings)
                for asset in request.assets:
                    try:
                        payload = base64.b64decode(asset.content_base64, validate=False)
                    except Exception as exc:
                        raise ValueError(
                            f"Invalid base64 for asset {asset.filename}."
                        ) from exc
                    store.save_asset(
                        document_id=document_id,
                        version_id=version_id,
                        asset_slug=asset_slug,
                        filename=asset.filename,
                        payload=payload,
                    )
                assets_written = True
                markdown_content = rewrite_local_image_refs(
                    markdown_content,
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
                markdown_content=markdown_content,
                asset_slug=asset_slug,
                draft_assets_root=assets_root,
            )
            if validation.has_blocking:
                raise ValueError(validation)

            original_metadata: dict[str, Any] = {}
            if request.original_asset_token:
                if request.source_type != "PDF":
                    raise ValueError("Original asset token is only valid for PDF documents.")
                original_metadata = original_store.commit_pending(
                    request.original_asset_token,
                    document_id=document_id,
                    version_id=version_id,
                    actor_id=actor.user_id,
                )
                original_asset_committed = True

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
                draft_version_id=version_id,
                status="DRAFT",
                etag=new_etag(document_id, 1),
                created_at=now,
                created_by=actor.user_id,
                updated_at=now,
                updated_by=actor.user_id,
                tenant_id=actor.tenant_id,
            )
            await self._repository.save_version(version)
            await self._repository.save_document(document)
            await self._ctx.audit(
                actor=actor,
                action="document.create",
                target_type="document",
                target_id=document_id,
                correlation_id=correlation_id,
                before=None,
                after={"status": document.status, "title": document.title},
            )
            response = await self._document_service.get_document(actor, document_id)
            if idempotency_key:
                await self._ctx.complete_idempotency(scope_key, payload_hash, response)
            return response
        except Exception:
            if assets_written:
                shutil.rmtree(
                    DraftAssetStore(self._settings).bundle_dir(document_id, version_id),
                    ignore_errors=True,
                )
            if original_asset_committed:
                original_store.remove_version(
                    document_id=document_id,
                    version_id=version_id,
                )
            raise

    async def update_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: UpdateDraftRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        detail = await self._document_service.get_document(actor, document_id)
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
        original_meta = {}
        if getattr(request, "original_asset_token", None):
            store = OriginalAssetStore(self._settings)
            original_meta = store.commit_pending(
                request.original_asset_token,
                document_id=document.document_id,
                version_id=version.version_id,
                actor_id=actor.user_id,
            )

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
                **original_meta,
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
            before={"status": document.status, "title": document.title, "category": document.category},
            after={"status": updated_document.status, "title": updated_document.title, "category": updated_document.category},
        )
        return await self._document_service.get_document(actor, document_id)

    async def validate_document(
        self, actor: PortalActor, document_id: str
    ) -> ValidationSummary:
        detail = await self._document_service.get_document(actor, document_id)
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
        detail = await self._document_service.get_document(actor, document_id)
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
            before={"status": document.status},
            after={"status": "DISCARDED"},
        )
        return {"document_id": document_id, "status": "DISCARDED"}

    async def start_revision(
        self,
        actor: PortalActor,
        document_id: str,
        correlation_id: str,
        change_reason: str = "Start a new revision from the published version.",
    ) -> DocumentDetailResponse:
        detail = await self._document_service.get_document(actor, document_id)
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
            source_type=published.source_type,
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
            original_asset_name=published.original_asset_name,
            original_asset_sha256=published.original_asset_sha256,
            original_asset_content_type=published.original_asset_content_type,
            original_asset_size=published.original_asset_size,
            etag=new_etag(published.content_hash, published.version_number + 1),
            created_at=now,
            created_by=actor.user_id,
        )
        OriginalAssetStore(self._settings).copy_version(
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
        await self._repository.save_version(version)
        await self._repository.save_document(updated_document)
        await self._ctx.audit(
            actor=actor,
            action="document.start_revision",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
            before={"status": document.status, "draftVersionId": document.draft_version_id},
            after={"status": updated_document.status, "draftVersionId": updated_document.draft_version_id},
        )
        return await self._document_service.get_document(actor, document_id)

    async def add_test_case(
        self,
        actor: PortalActor,
        document_id: str,
        request: CreateTestCaseRequest,
        correlation_id: str,
    ) -> TestCaseRecord:
        detail = await self._document_service.get_document(actor, document_id)
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

    async def search_draft(
        self,
        actor: PortalActor,
        document_id: str,
        query: str,
        groups: list[str] | None = None,
        limit: int = 4,
    ):
        detail = await self._document_service.get_document(actor, document_id)
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
        detail = await self._document_service.get_document(actor, document_id)
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
        detail = await self._document_service.get_document(actor, document_id)
        if detail.draft_version is None:
            return []
        return await self._repository.list_test_cases(detail.draft_version.version_id)

    async def list_test_runs(
        self,
        actor: PortalActor,
        document_id: str,
        test_case_id: str | None = None,
    ) -> list[TestRunRecord]:
        detail = await self._document_service.get_document(actor, document_id)
        if detail.draft_version is None:
            return []
        runs = await self._repository.list_test_runs(detail.draft_version.version_id)
        if test_case_id is not None:
            return [item for item in runs if item.test_case_id == test_case_id]
        return runs
