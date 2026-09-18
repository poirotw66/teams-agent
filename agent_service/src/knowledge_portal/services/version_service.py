"""Version and draft lifecycle service facade.

Handles draft creation, validation, revisions, and draft test cases (A08).
Command bodies live in sibling ``version_*`` modules.
"""

from __future__ import annotations

from typing import Any

from ..models import (
    CreateDocumentRequest,
    CreateTestCaseRequest,
    DocumentDetailResponse,
    PortalActor,
    RemoveDocumentRequest,
    TestCaseRecord,
    TestRunRecord,
    UpdateDraftRequest,
    ValidationSummary,
)
from . import version_create, version_draft, version_revision, version_test_cases
from .context import PortalServiceContext


class VersionService:
    """Service handling draft creation, revisions, and test cases."""

    def __init__(self, ctx: PortalServiceContext, document_service: Any = None) -> None:
        self._ctx = ctx
        self._document_service = document_service

    async def create_document(
        self,
        actor: PortalActor,
        request: CreateDocumentRequest,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> DocumentDetailResponse:
        return await version_create.create_document(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            request=request,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    async def update_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: UpdateDraftRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        return await version_draft.update_draft(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            document_id=document_id,
            request=request,
            correlation_id=correlation_id,
        )

    async def validate_document(self, actor: PortalActor, document_id: str) -> ValidationSummary:
        return await version_draft.validate_document(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            document_id=document_id,
        )

    async def discard_draft(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> dict[str, str]:
        return await version_draft.discard_draft(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            document_id=document_id,
            request=request,
            correlation_id=correlation_id,
        )

    async def start_revision(
        self,
        actor: PortalActor,
        document_id: str,
        correlation_id: str,
        change_reason: str = "Start a new revision from the published version.",
    ) -> DocumentDetailResponse:
        return await version_revision.start_revision(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            document_id=document_id,
            correlation_id=correlation_id,
            change_reason=change_reason,
        )

    async def add_test_case(
        self,
        actor: PortalActor,
        document_id: str,
        request: CreateTestCaseRequest,
        correlation_id: str,
    ) -> TestCaseRecord:
        return await version_test_cases.add_test_case(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            document_id=document_id,
            request=request,
            correlation_id=correlation_id,
        )

    async def search_draft(
        self,
        actor: PortalActor,
        document_id: str,
        query: str,
        groups: list[str] | None = None,
        limit: int = 4,
    ):
        return await version_test_cases.search_draft(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            document_id=document_id,
            query=query,
            groups=groups,
            limit=limit,
        )

    async def run_test_case(
        self,
        actor: PortalActor,
        document_id: str,
        test_case_id: str,
        correlation_id: str,
    ) -> TestRunRecord:
        return await version_test_cases.run_test_case(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            document_id=document_id,
            test_case_id=test_case_id,
            correlation_id=correlation_id,
        )

    async def list_test_cases(self, actor: PortalActor, document_id: str) -> list[TestCaseRecord]:
        return await version_test_cases.list_test_cases(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            document_id=document_id,
        )

    async def list_test_runs(
        self,
        actor: PortalActor,
        document_id: str,
        test_case_id: str | None = None,
    ) -> list[TestRunRecord]:
        return await version_test_cases.list_test_runs(
            ctx=self._ctx,
            documents=self._document_service,
            actor=actor,
            document_id=document_id,
            test_case_id=test_case_id,
        )
