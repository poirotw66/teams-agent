from __future__ import annotations

from ..models import (
    DocumentDetailResponse,
    PendingReviewItem,
    PendingReviewListResponse,
    PortalActor,
    ReviewDecisionRequest,
    ReviewRecord,
    SubmitReviewRequest,
    utc_now,
)
from ..rbac import (
    PortalPermissionError,
    ensure_can_edit,
    ensure_can_review,
    ensure_document_visible,
    ensure_not_found,
)
from ..role_capabilities import ensure_can_list_pending_reviews
from ..repository import VersionConflictError, new_id
from ..review_context import build_pending_review_context
from ..validation import validate_draft
from .context import PortalServiceContext
from .document_service import DocumentService


class ReviewService:
    def __init__(self, ctx: PortalServiceContext, documents: DocumentService) -> None:
        self._ctx = ctx
        self._documents = documents

    async def list_pending_reviews(
        self, actor: PortalActor
    ) -> PendingReviewListResponse:
        ensure_can_list_pending_reviews(actor)
        reviews = await self._ctx.repository.list_pending_reviews(actor)
        items: list[PendingReviewItem] = []
        for review in reviews:
            document = await self._ctx.repository.get_document(review.document_id)
            if document is None:
                continue
            try:
                ensure_document_visible(
                    actor, document.owner_unit_id, document.created_by
                )
            except PortalPermissionError:
                continue
            context = await build_pending_review_context(
                self._ctx.repository,
                document,
                review.version_id,
                self._ctx.settings,
            )
            items.append(
                PendingReviewItem(
                    review_id=review.review_id,
                    document_id=review.document_id,
                    document_title=document.title,
                    submitted_by=review.submitted_by,
                    submitted_at=review.submitted_at,
                    owner_unit_id=str(context["owner_unit_id"]),
                    change_reason=str(context["change_reason"]),
                    audience_label=str(context["audience_label"]),
                    audience_changed=bool(context["audience_changed"]),
                    test_summary=context["test_summary"],  # type: ignore[arg-type]
                )
            )
        return PendingReviewListResponse(items=items, total=len(items))

    async def submit_for_review(
        self,
        actor: PortalActor,
        document_id: str,
        request: SubmitReviewRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        detail = await self._documents.get_document(actor, document_id)
        document = detail.document
        ensure_can_edit(actor, document.owner_unit_id, document.created_by)
        if document.etag != request.etag:
            raise VersionConflictError(document_id)
        if detail.draft_version is None:
            raise ValueError("Document has no draft version.")
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
            change_reason=request.change_reason,
            effective_at=version.effective_at,
            review_due_at=version.review_due_at,
            audience_type=version.audience_type,
            audience_group_ids=version.audience_group_ids,
            markdown_content=version.canonical_content,
            asset_slug=asset_slug,
            draft_assets_root=assets_root,
        )
        if validation.has_blocking:
            raise ValueError(validation)
        if not self._ctx.settings.effective_relaxed_workflow():
            test_cases = await self._ctx.repository.list_test_cases(version.version_id)
            if len(test_cases) < 3:
                raise ValueError(
                    "At least three test questions are required before review."
                )

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
        await self._ctx.repository.save_review(review)
        await self._ctx.repository.save_version(updated_version)
        await self._ctx.repository.save_document(updated_document)
        await self._ctx.audit(
            actor=actor,
            action="review.submit",
            target_type="version",
            target_id=version.version_id,
            correlation_id=correlation_id,
            reason=request.change_reason,
        )
        return await self._documents.get_document(actor, document_id)

    async def decide_review(
        self,
        actor: PortalActor,
        review_id: str,
        request: ReviewDecisionRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        review = await self._ctx.repository.get_review(review_id)
        ensure_not_found("review", review_id, review)
        if review.decision is not None:
            raise ValueError("Review has already been decided.")
        ensure_can_review(
            actor,
            review.submitted_by,
            relaxed_workflow=self._ctx.settings.effective_relaxed_workflow(),
        )
        version = await self._ctx.repository.get_version(review.version_id)
        ensure_not_found("version", review.version_id, version)
        document = await self._ctx.repository.get_document(review.document_id)
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
        await self._ctx.repository.save_review(updated_review)
        await self._ctx.repository.save_version(updated_version)
        await self._ctx.repository.save_document(updated_document)
        await self._ctx.audit(
            actor=actor,
            action=f"review.{request.decision.lower()}",
            target_type="review",
            target_id=review_id,
            correlation_id=correlation_id,
            reason=request.comment,
        )
        return await self._documents.get_document(actor, document.document_id)
