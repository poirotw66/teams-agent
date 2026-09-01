from __future__ import annotations

from .models import (
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PendingReviewTestSummary,
)
from .repository import PortalRepository
from .settings import PortalSettings


def audience_label(audience_type: str, group_ids: list[str]) -> str:
    if audience_type == "ALL_EMPLOYEES":
        return "全體員工"
    if group_ids:
        return "、".join(group_ids)
    return "特定群組"


def audience_changed(
    draft: KnowledgeVersionRecord | None,
    published: KnowledgeVersionRecord | None,
) -> bool:
    if draft is None or published is None:
        return False
    if draft.audience_type != published.audience_type:
        return True
    return set(draft.audience_group_ids) != set(published.audience_group_ids)


async def build_test_summary(
    repository: PortalRepository,
    version_id: str,
    *,
    min_required: int,
) -> PendingReviewTestSummary:
    cases = await repository.list_test_cases(version_id)
    runs = await repository.list_test_runs(version_id)
    latest_by_case: dict[str, str] = {}
    for run in sorted(runs, key=lambda item: item.executed_at):
        latest_by_case[run.test_case_id] = run.status

    pass_count = sum(1 for status in latest_by_case.values() if status == "PASS")
    needs_review_count = sum(
        1 for status in latest_by_case.values() if status == "NEEDS_REVIEW"
    )
    fail_count = sum(1 for status in latest_by_case.values() if status == "FAIL")

    return PendingReviewTestSummary(
        total=len(cases),
        executed=len(latest_by_case),
        pass_count=pass_count,
        needs_review_count=needs_review_count,
        fail_count=fail_count,
        meets_minimum=len(cases) >= min_required,
    )


async def build_pending_review_context(
    repository: PortalRepository,
    document: KnowledgeDocumentRecord,
    version_id: str,
    settings: PortalSettings,
) -> dict[str, object]:
    version = await repository.get_version(version_id)
    published = None
    if document.current_published_version_id:
        published = await repository.get_version(document.current_published_version_id)

    min_required = 0 if settings.effective_relaxed_workflow() else 3
    test_summary = await build_test_summary(
        repository,
        version_id,
        min_required=min_required,
    )

    draft = version
    return {
        "owner_unit_id": document.owner_unit_id,
        "change_reason": draft.change_reason if draft else "",
        "audience_label": audience_label(
            draft.audience_type if draft else document.audience_type,
            draft.audience_group_ids if draft else document.audience_group_ids,
        ),
        "audience_changed": audience_changed(draft, published),
        "test_summary": test_summary,
    }
