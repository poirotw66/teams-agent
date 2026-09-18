"""Draft test-case workflows for VersionService (A08)."""

from __future__ import annotations

from typing import Protocol

from ..draft_retrieval import evaluate_test_case, search_draft_version
from ..models import (
    CreateTestCaseRequest,
    DocumentDetailResponse,
    PortalActor,
    TestCaseRecord,
    TestRunRecord,
    utc_now,
)
from ..rbac import ensure_not_found
from ..repository import new_id
from .context import PortalServiceContext


class DocumentLookup(Protocol):
    async def get_document(
        self, actor: PortalActor, document_id: str
    ) -> DocumentDetailResponse: ...


async def add_test_case(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    document_id: str,
    request: CreateTestCaseRequest,
    correlation_id: str,
) -> TestCaseRecord:
    detail = await documents.get_document(actor, document_id)
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
    await ctx.repository.save_test_case(test_case)
    await ctx.audit(
        actor=actor,
        action="test_case.create",
        target_type="test_case",
        target_id=test_case.test_case_id,
        correlation_id=correlation_id,
    )
    return test_case


async def search_draft(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    document_id: str,
    query: str,
    groups: list[str] | None = None,
    limit: int = 4,
):
    detail = await documents.get_document(actor, document_id)
    if detail.draft_version is None:
        raise ValueError("Draft version is required.")
    return search_draft_version(
        version=detail.draft_version,
        query=query,
        groups=groups or [],
        settings=ctx.settings,
        limit=limit,
    )


async def run_test_case(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    document_id: str,
    test_case_id: str,
    correlation_id: str,
) -> TestRunRecord:
    detail = await documents.get_document(actor, document_id)
    if detail.draft_version is None:
        raise ValueError("Draft version is required.")
    cases = await ctx.repository.list_test_cases(detail.draft_version.version_id)
    test_case = next((item for item in cases if item.test_case_id == test_case_id), None)
    ensure_not_found("test_case", test_case_id, test_case)

    status, answer_excerpt, cited_titles, failure_reason = evaluate_test_case(
        version=detail.draft_version,
        question=test_case.question,
        simulated_audience=test_case.simulated_audience,
        settings=ctx.settings,
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
    await ctx.repository.save_test_run(test_run)
    await ctx.audit(
        actor=actor,
        action="test_case.run",
        target_type="test_case",
        target_id=test_case_id,
        correlation_id=correlation_id,
        metadata={"status": status},
    )
    return test_run


async def list_test_cases(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    document_id: str,
) -> list[TestCaseRecord]:
    detail = await documents.get_document(actor, document_id)
    if detail.draft_version is None:
        return []
    return await ctx.repository.list_test_cases(detail.draft_version.version_id)


async def list_test_runs(
    *,
    ctx: PortalServiceContext,
    documents: DocumentLookup,
    actor: PortalActor,
    document_id: str,
    test_case_id: str | None = None,
) -> list[TestRunRecord]:
    detail = await documents.get_document(actor, document_id)
    if detail.draft_version is None:
        return []
    runs = await ctx.repository.list_test_runs(detail.draft_version.version_id)
    if test_case_id is not None:
        return [item for item in runs if item.test_case_id == test_case_id]
    return runs
