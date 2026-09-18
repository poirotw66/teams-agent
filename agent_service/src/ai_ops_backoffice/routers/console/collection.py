"""Work-item collection helpers for console aggregation."""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime
from typing import Any

from agent_service.operations.access import ActorContext

from .models import WorkItem, WorkItemAction

logger = logging.getLogger(__name__)

_STEP_LABELS = {
    "NEW": "待分流",
    "TRIAGED": "已確認方向",
    "IN_PROGRESS": "修正中",
    "WAITING_REVIEW": "等待審核或驗證",
    "OBSERVING": "已進入觀察",
    "RESOLVED": "已驗證結案",
    "WONT_FIX": "不予修復",
    "DUPLICATE": "重複案件",
}
_ACTION_IDS = {
    "NEW": "triage_case",
    "TRIAGED": "start_progress",
    "IN_PROGRESS": "link_fix",
    "WAITING_REVIEW": "verify_review",
    "OBSERVING": "check_observation",
}


def encode_cursor(offset: int, actor_id: str, snapshot_id: str) -> str:
    raw = json.dumps({"o": offset, "a": actor_id, "s": snapshot_id})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str, actor_id: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        if data.get("a") != actor_id:
            return 0
        return max(0, int(data.get("o", 0)))
    except Exception:
        return 0


def _bucket_for_quality_status(status: str) -> str:
    if status in {"NEW", "TRIAGED", "IN_PROGRESS"}:
        return "pending_action"
    if status == "WAITING_REVIEW":
        return "pending_review"
    if status == "OBSERVING":
        return "tracking"
    return "completed"


def build_quality_case_work_item(case: dict[str, Any]) -> tuple[str, WorkItem]:
    status = str(case.get("status", "NEW")).upper()
    case_id = str(case.get("case_id", ""))
    due_at = case.get("target_due_at")
    due_at_str = due_at.isoformat() if hasattr(due_at, "isoformat") else (str(due_at) if due_at else None)
    updated_at = case.get("updated_at")
    updated_at_str = (
        updated_at.isoformat()
        if hasattr(updated_at, "isoformat")
        else (str(updated_at) if updated_at else datetime.now(UTC).isoformat())
    )
    item = WorkItem(
        key=f"quality_case:{case_id}:{status.lower()}",
        workflow="quality_improvement",
        source_type="quality_case",
        source_id=case_id,
        title=str(case.get("title", "")),
        owner_unit_id=str(case.get("owner_unit_id", "")),
        assignee_id=case.get("assignee_id"),
        source_status=status,
        step=_STEP_LABELS.get(status, status),
        next_action=WorkItemAction(
            id=_ACTION_IDS.get(status, "view_case"),
            route=f"/console-v2/improvements/cases/{case_id}",
        ),
        blocked_reason=None,
        due_at=due_at_str,
        updated_at=updated_at_str,
        revision=str(case.get("etag", 1)),
    )
    return _bucket_for_quality_status(status), item


def collect_quality_items(
    quality_service: Any,
    actor: ActorContext,
    owner_unit_id: str | None = None,
) -> tuple[list[tuple[str, WorkItem]], str]:
    if quality_service is None or not actor.has_capability("ops.quality.read"):
        return [], "ok"
    try:
        cases = quality_service.list_cases(actor=actor, owner_unit_id=owner_unit_id)
        results = [build_quality_case_work_item(case) for case in cases]
        return results, "ok"
    except Exception as err:
        logger.warning("Failed to collect quality work items: %s", err, exc_info=True)
        return [], "unavailable"


def collect_knowledge_items(
    knowledge_client: Any,
    actor: ActorContext,
) -> tuple[list[tuple[str, WorkItem]], str]:
    if knowledge_client is None or not getattr(knowledge_client, "configured", False):
        return [], "ok"
    if not (actor.has_capability("knowledge.review") or actor.has_capability("knowledge.review.ui")):
        return [], "ok"
    return [], "ok"
