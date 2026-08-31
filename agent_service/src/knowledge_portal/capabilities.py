from __future__ import annotations

from .models import KnowledgeDocumentRecord, KnowledgeVersionRecord, PortalActor, ReviewRecord
from .rbac import (
    can_edit_document,
    can_view_document,
    ensure_can_publish,
    ensure_can_remove_document,
    ensure_can_review,
)
from .settings import PortalSettings

PortalAction = str

STATUS_LABELS: dict[str, str] = {
    "DRAFT": "草稿",
    "IN_REVIEW": "待審核",
    "CHANGES_REQUESTED": "待修正",
    "APPROVED": "已核准",
    "PUBLISHING": "發布中",
    "PUBLISHED": "已發布",
    "PUBLISH_FAILED": "發布失敗",
    "UNPUBLISHED": "已下架",
    "DISCARDED": "已放棄",
    "REJECTED": "已拒絕",
}

TEST_RESULT_LABELS: dict[str, str] = {
    "PASS": "可回答",
    "NEEDS_REVIEW": "需要確認",
    "FAIL": "無法回答",
}

NEXT_ACTION_LABELS: dict[str, str] = {
    "EDIT_DRAFT": "編輯草稿",
    "SUBMIT_REVIEW": "送審",
    "APPROVE": "核准",
    "REJECT": "退回修改",
    "PUBLISH": "發布正式版本",
    "START_REVISION": "建立新版本",
    "VIEW": "查看內容",
}


def document_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def test_result_label(status: str) -> str:
    return TEST_RESULT_LABELS.get(status, status)


def next_action_label(action: str | None) -> str:
    if not action:
        return ""
    return NEXT_ACTION_LABELS.get(action, action)


def _can(action: str, allowed: list[str]) -> bool:
    return action in allowed


def _try_review(actor: PortalActor, submitted_by: str, settings: PortalSettings) -> bool:
    try:
        ensure_can_review(actor, submitted_by, relaxed_workflow=settings.effective_relaxed_workflow())
        return True
    except Exception:
        return False


def _try_publish(actor: PortalActor) -> bool:
    try:
        ensure_can_publish(actor)
        return True
    except Exception:
        return False


def _try_discard(actor: PortalActor, document: KnowledgeDocumentRecord, settings: PortalSettings) -> bool:
    try:
        ensure_can_remove_document(actor, document, relaxed_workflow=settings.effective_relaxed_workflow())
        return document.status != "IN_REVIEW" and not (
            document.current_published_version_id and document.status == "PUBLISHED"
        )
    except Exception:
        return False


def _try_unpublish(actor: PortalActor, document: KnowledgeDocumentRecord) -> bool:
    if document.status != "PUBLISHED":
        return False
    return _try_publish(actor)


def compute_allowed_actions(
    *,
    actor: PortalActor,
    document: KnowledgeDocumentRecord,
    draft_version: KnowledgeVersionRecord | None,
    open_review: ReviewRecord | None,
    settings: PortalSettings,
) -> list[PortalAction]:
    if not can_view_document(actor, document.owner_unit_id, document.created_by):
        return []

    actions: list[PortalAction] = ["VIEW"]

    if draft_version and can_edit_document(actor, document.owner_unit_id, document.created_by):
        if document.status in {"DRAFT", "CHANGES_REQUESTED", "APPROVED"}:
            actions.extend(["EDIT_DRAFT", "VALIDATE", "MANAGE_TESTS"])

    if (
        draft_version
        and document.status in {"DRAFT", "CHANGES_REQUESTED"}
        and can_edit_document(actor, document.owner_unit_id, document.created_by)
    ):
        actions.append("SUBMIT_REVIEW")

    if open_review and _try_review(actor, open_review.submitted_by, settings):
        actions.extend(["APPROVE", "REJECT"])

    if (
        document.status == "APPROVED"
        and draft_version
        and _try_publish(actor)
    ):
        actions.append("PUBLISH")

    if (
        document.status == "PUBLISHED"
        and not document.draft_version_id
        and can_edit_document(actor, document.owner_unit_id, document.created_by)
    ):
        actions.append("START_REVISION")

    if _try_discard(actor, document, settings):
        actions.append("DISCARD_DRAFT")

    if _try_unpublish(actor, document):
        actions.append("UNPUBLISH")

    return list(dict.fromkeys(actions))


def compute_next_action(
    allowed_actions: list[PortalAction],
    *,
    document_status: str,
) -> str | None:
    if document_status == "IN_REVIEW" and "APPROVE" in allowed_actions:
        return "APPROVE"
    if document_status == "APPROVED" and "PUBLISH" in allowed_actions:
        return "PUBLISH"
    if document_status in {"DRAFT", "CHANGES_REQUESTED"} and "SUBMIT_REVIEW" in allowed_actions:
        return "SUBMIT_REVIEW"
    if "EDIT_DRAFT" in allowed_actions:
        return "EDIT_DRAFT"
    if document_status == "PUBLISHED" and "START_REVISION" in allowed_actions:
        return "START_REVISION"
    if "VIEW" in allowed_actions:
        return "VIEW"
    return None
