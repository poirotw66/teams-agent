from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from agent_service.knowledge_release import write_active_release_pointer

from .models import (
    AuditEventRecord,
    CreateDocumentRequest,
    CreateTestCaseRequest,
    DashboardSummary,
    DocumentDetailResponse,
    DocumentListResponse,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    PublishRequest,
    ReleaseRecord,
    ReviewDecisionRequest,
    ReviewRecord,
    RollbackRequest,
    SubmitReviewRequest,
    TestCaseRecord,
    TestRunRecord,
    UpdateDraftRequest,
    ValidationSummary,
    new_etag,
    utc_now,
)
from .draft_retrieval import evaluate_test_case, search_draft_version
from .migration import KnowledgeMigrationService
from .publisher import ReleasePublisher
from .rbac import (
    ensure_can_edit,
    ensure_can_publish,
    ensure_can_review,
    ensure_document_visible,
    ensure_not_found,
)
from .repository import (
    PortalNotFoundError,
    PortalRepository,
    VersionConflictError,
    new_id,
)
from .settings import PortalSettings
from .validation import (
    build_front_matter_markdown,
    build_parse_preview,
    content_hash,
    validate_draft,
)


class PortalService:
    def __init__(self, settings: PortalSettings, repository: PortalRepository) -> None:
        self._settings = settings
        self._repository = repository
        self._publisher = ReleasePublisher(settings)
        self._migration = KnowledgeMigrationService(settings, repository, self._publisher)

    async def _audit(
        self,
        *,
        actor: PortalActor,
        action: str,
        target_type: str,
        target_id: str,
        correlation_id: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        result: str = "SUCCESS",
    ) -> None:
        await self._repository.append_audit(
            AuditEventRecord(
                event_id=new_id("audit"),
                actor_id=actor.user_id,
                actor_role=actor.role,
                action=action,
                target_type=target_type,
                target_id=target_id,
                correlation_id=correlation_id,
                reason=reason,
                result=result,
                occurred_at=utc_now(),
                metadata=metadata or {},
            )
        )

    async def dashboard(self, actor: PortalActor) -> DashboardSummary:
        return await self._repository.dashboard_summary(actor)

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
        return DocumentDetailResponse(
            document=document,
            draft_version=draft_version,
            published_version=published_version,
            open_review=open_review,
        )

    async def create_document(
        self,
        actor: PortalActor,
        request: CreateDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        validation = validate_draft(
            title=request.title,
            owner_unit_id=request.owner_unit_id,
            change_reason=request.change_reason,
            effective_at=request.effective_at,
            review_due_at=request.review_due_at,
            audience_type=request.audience_type,
            audience_group_ids=request.audience_group_ids,
            markdown_content=request.markdown_content,
        )
        if validation.has_blocking:
            raise ValueError(validation)

        now = utc_now()
        document_id = new_id("doc")
        version_id = new_id("ver")
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
        await self._audit(
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
        if document.status not in {"DRAFT", "CHANGES_REQUESTED"}:
            raise ValueError("Only draft documents can be edited.")
        if document.etag != request.etag:
            raise VersionConflictError(document_id)
        if not document.draft_version_id:
            raise ValueError("Document has no editable draft version.")

        version = await self._repository.get_version(document.draft_version_id)
        ensure_not_found("version", document.draft_version_id, version)
        if version.status not in {"DRAFT", "CHANGES_REQUESTED"}:
            raise ValueError("Draft version is locked for editing.")

        validation = validate_draft(
            title=request.title,
            owner_unit_id=request.owner_unit_id,
            change_reason=request.change_reason,
            effective_at=request.effective_at,
            review_due_at=request.review_due_at,
            audience_type=request.audience_type,
            audience_group_ids=request.audience_group_ids,
            markdown_content=request.markdown_content,
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
        await self._audit(
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
        return detail.draft_version.validation_summary

    async def submit_for_review(
        self,
        actor: PortalActor,
        document_id: str,
        request: SubmitReviewRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        detail = await self.get_document(actor, document_id)
        document = detail.document
        ensure_can_edit(actor, document.owner_unit_id, document.created_by)
        if document.etag != request.etag:
            raise VersionConflictError(document_id)
        if detail.draft_version is None:
            raise ValueError("Document has no draft version.")
        version = detail.draft_version
        validation = validate_draft(
            title=version.title,
            owner_unit_id=version.owner_unit_id,
            change_reason=request.change_reason,
            effective_at=version.effective_at,
            review_due_at=version.review_due_at,
            audience_type=version.audience_type,
            audience_group_ids=version.audience_group_ids,
            markdown_content=version.canonical_content,
        )
        if validation.has_blocking:
            raise ValueError(validation)
        test_cases = await self._repository.list_test_cases(version.version_id)
        if len(test_cases) < 3:
            raise ValueError("At least three test questions are required before review.")

        review = ReviewRecord(
            review_id=new_id("review"),
            version_id=version.version_id,
            document_id=document.document_id,
            snapshot_hash=version.content_hash,
            submitted_by=actor.user_id,
            submitted_at=utc_now(),
        )
        updated_version = version.model_copy(update={"status": "IN_REVIEW"})
        updated_document = document.model_copy(
            update={
                "status": "IN_REVIEW",
                "updated_at": utc_now(),
                "updated_by": actor.user_id,
            }
        )
        await self._repository.save_review(review)
        await self._repository.save_version(updated_version)
        await self._repository.save_document(updated_document)
        await self._audit(
            actor=actor,
            action="review.submit",
            target_type="version",
            target_id=version.version_id,
            correlation_id=correlation_id,
            reason=request.change_reason,
        )
        return await self.get_document(actor, document_id)

    async def decide_review(
        self,
        actor: PortalActor,
        review_id: str,
        request: ReviewDecisionRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        reviews = await self._repository.list_pending_reviews(actor)
        review = await self._repository.get_review(review_id)
        ensure_not_found("review", review_id, review)
        if review.decision is not None:
            raise ValueError("Review has already been decided.")
        ensure_can_review(actor, review.submitted_by)
        version = await self._repository.get_version(review.version_id)
        ensure_not_found("version", review.version_id, version)
        document = await self._repository.get_document(review.document_id)
        ensure_not_found("document", review.document_id, document)

        now = utc_now()
        updated_review = review.model_copy(
            update={
                "reviewer_id": actor.user_id,
                "decision": request.decision,
                "comment": request.comment,
                "decided_at": now,
                "policy_exceptions": request.policy_exceptions,
            }
        )
        if request.decision == "APPROVED":
            version_status = "APPROVED"
            document_status = "APPROVED"
        elif request.decision == "CHANGES_REQUESTED":
            version_status = "CHANGES_REQUESTED"
            document_status = "CHANGES_REQUESTED"
        else:
            version_status = "REJECTED"
            document_status = "DRAFT"

        updated_version = version.model_copy(update={"status": version_status})
        updated_document = document.model_copy(
            update={
                "status": document_status,
                "updated_at": now,
                "updated_by": actor.user_id,
            }
        )
        await self._repository.save_review(updated_review)
        await self._repository.save_version(updated_version)
        await self._repository.save_document(updated_document)
        await self._audit(
            actor=actor,
            action=f"review.{request.decision.lower()}",
            target_type="review",
            target_id=review_id,
            correlation_id=correlation_id,
            reason=request.comment,
        )
        return await self.get_document(actor, document.document_id)

    async def publish_version(
        self,
        actor: PortalActor,
        document_id: str,
        request: PublishRequest,
        correlation_id: str,
    ) -> ReleaseRecord:
        ensure_can_publish(actor)
        detail = await self.get_document(actor, document_id)
        document = detail.document
        version = await self._repository.get_version(request.version_id)
        ensure_not_found("version", request.version_id, version)
        if version.document_id != document_id:
            raise ValueError("Version does not belong to this document.")
        if version.status != "APPROVED":
            raise ValueError("Only approved versions can be published.")
        if (
            self._settings.require_dual_approval
            and actor.user_id == version.created_by
            and actor.role != "PLATFORM"
        ):
            raise ValueError("Contributors cannot publish their own approved content.")

        all_versions = await self._repository.list_versions_for_document(document_id)
        published_versions = [
            item
            for item in all_versions
            if item.status == "PUBLISHED" and item.version_id != version.version_id
        ]
        published_versions.append(version.model_copy(update={"status": "PUBLISHED"}))

        other_documents = await self._repository.list_documents(actor=actor)
        for other in other_documents:
            if other.document_id == document_id or not other.current_published_version_id:
                continue
            other_version = await self._repository.get_version(
                other.current_published_version_id
            )
            if other_version is not None and other_version.status == "PUBLISHED":
                published_versions.append(other_version)

        release_id = new_id("release")
        previous_release_id = await self._repository.get_active_release_id()
        try:
            release = self._publisher.build_release(
                release_id=release_id,
                published_versions=published_versions,
                created_by=actor.user_id,
                previous_release_id=previous_release_id,
            )
        except ReleaseBuildError as exc:
            await self._audit(
                actor=actor,
                action="release.failed",
                target_type="release",
                target_id=release_id,
                correlation_id=correlation_id,
                reason=str(exc),
                result="FAILURE",
            )
            raise

        release = release.model_copy(
            update={
                "status": "ACTIVE",
                "activated_at": utc_now(),
                "verified_at": utc_now(),
                "approved_by": actor.user_id,
            }
        )
        await self._repository.save_release(release)
        await self._repository.set_active_release_id(release.release_id)
        write_active_release_pointer(
            self._settings.release_artifact_dir,
            release.release_id,
        )

        updated_version = version.model_copy(update={"status": "PUBLISHED"})
        updated_document = document.model_copy(
            update={
                "status": "PUBLISHED",
                "current_published_version_id": version.version_id,
                "draft_version_id": None,
                "updated_at": utc_now(),
                "updated_by": actor.user_id,
            }
        )
        await self._repository.save_version(updated_version)
        await self._repository.save_document(updated_document)
        await self._audit(
            actor=actor,
            action="release.activate",
            target_type="release",
            target_id=release.release_id,
            correlation_id=correlation_id,
            reason=request.reason,
            metadata={"documentId": document_id, "versionId": version.version_id},
        )
        return release

    async def rollback_release(
        self,
        actor: PortalActor,
        request: RollbackRequest,
        correlation_id: str,
    ) -> ReleaseRecord:
        ensure_can_publish(actor)
        target = await self._repository.get_release(request.release_id)
        ensure_not_found("release", request.release_id, target)
        await self._repository.set_active_release_id(target.release_id)
        write_active_release_pointer(
            self._settings.release_artifact_dir,
            target.release_id,
        )
        rolled_back = target.model_copy(update={"status": "ACTIVE", "activated_at": utc_now()})
        await self._repository.save_release(rolled_back)
        await self._audit(
            actor=actor,
            action="release.rollback",
            target_type="release",
            target_id=target.release_id,
            correlation_id=correlation_id,
            reason=request.reason,
        )
        return rolled_back

    async def list_releases(self, actor: PortalActor) -> list[ReleaseRecord]:
        return await self._repository.list_releases()

    async def list_audit(self, actor: PortalActor, *, limit: int = 100):
        return await self._repository.list_audit_events(limit=limit)

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
        await self._audit(
            actor=actor,
            action="test_case.create",
            target_type="test_case",
            target_id=test_case.test_case_id,
            correlation_id=correlation_id,
        )
        return test_case

    async def bootstrap_release_0001(
        self,
        actor: PortalActor,
        sources_dir: Path,
        correlation_id: str,
        release_id: str = "release-0001",
    ) -> ReleaseRecord:
        return await self._migration.bootstrap_release_0001(
            actor=actor,
            sources_dir=sources_dir,
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
        await self._audit(
            actor=actor,
            action="test_case.run",
            target_type="test_case",
            target_id=test_case_id,
            correlation_id=correlation_id,
            metadata={"status": status},
        )
        return test_run

    async def list_test_cases(self, actor: PortalActor, document_id: str) -> list[TestCaseRecord]:
        detail = await self.get_document(actor, document_id)
        if detail.draft_version is None:
            return []
        return await self._repository.list_test_cases(detail.draft_version.version_id)

    async def list_test_runs(self, actor: PortalActor, document_id: str) -> list[TestRunRecord]:
        detail = await self.get_document(actor, document_id)
        if detail.draft_version is None:
            return []
        return await self._repository.list_test_runs(detail.draft_version.version_id)
