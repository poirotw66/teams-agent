"""Console aggregation and workflow routes for AI Ops Backoffice (Console V2)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from agent_service.operations.access import ActorContext

logger = logging.getLogger(__name__)

WORKFLOW_KINDS = {"quality_case", "knowledge_doc", "eval_gate"}
VALID_BUCKETS = {"all", "pending_action", "pending_review", "tracking", "completed"}


class WorkItemAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    route: str


class WorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str
    workflow: str
    source_type: str
    source_id: str
    title: str
    owner_unit_id: str
    assignee_id: str | None = None
    source_status: str
    step: str
    next_action: WorkItemAction
    blocked_reason: str | None = None
    due_at: str | None = None
    updated_at: str
    revision: str


class WorkItemsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: list[WorkItem]
    next_cursor: str | None = None
    total: int
    snapshot_id: str
    generated_at: str
    partial: bool
    sources: dict[str, str]


class WorkSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    total: int
    by_bucket: dict[str, int]
    by_workflow: dict[str, int]
    sources: dict[str, str]
    snapshot_id: str
    generated_at: str


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_type: str
    source_id: str
    version_hash: str | None = None
    relation: str
    occurred_at: str | None = None
    retrieved_at: str
    validity: Literal["valid", "stale", "unknown", "revoked"]


class WorkflowStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    status: Literal["pending", "current", "completed", "skipped", "failed"]


class WorkflowDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    id: str
    title: str
    status: str
    stages: list[WorkflowStage]
    evidence_refs: list[EvidenceRef]
    allowed_actions: list[str]
    return_route: str


def _encode_cursor(offset: int, actor_id: str, snapshot_id: str) -> str:
    raw = json.dumps({"o": offset, "a": actor_id, "s": snapshot_id})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor: str, actor_id: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        if data.get("a") != actor_id:
            return 0
        return max(0, int(data.get("o", 0)))
    except Exception:
        return 0


def _build_quality_case_work_item(case: dict[str, Any]) -> tuple[str, WorkItem]:
    status = str(case.get("status", "NEW")).upper()
    case_id = str(case.get("case_id", ""))

    if status in {"NEW", "TRIAGED", "IN_PROGRESS"}:
        bucket = "pending_action"
    elif status == "WAITING_REVIEW":
        bucket = "pending_review"
    elif status == "OBSERVING":
        bucket = "tracking"
    else:
        bucket = "completed"

    step_labels = {
        "NEW": "待分流",
        "TRIAGED": "已確認方向",
        "IN_PROGRESS": "修正中",
        "WAITING_REVIEW": "等待審核或驗證",
        "OBSERVING": "已進入觀察",
        "RESOLVED": "已驗證結案",
        "WONT_FIX": "不予修復",
        "DUPLICATE": "重複案件",
    }
    action_ids = {
        "NEW": "triage_case",
        "TRIAGED": "start_progress",
        "IN_PROGRESS": "link_fix",
        "WAITING_REVIEW": "verify_review",
        "OBSERVING": "check_observation",
    }

    step_text = step_labels.get(status, status)
    action_id = action_ids.get(status, "view_case")
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
        step=step_text,
        next_action=WorkItemAction(
            id=action_id,
            route=f"/console-v2/improvements/cases/{case_id}",
        ),
        blocked_reason=None,
        due_at=due_at_str,
        updated_at=updated_at_str,
        revision=str(case.get("etag", 1)),
    )
    return bucket, item


def _collect_quality_items(
    quality_service: Any,
    actor: ActorContext,
    owner_unit_id: str | None = None,
) -> tuple[list[tuple[str, WorkItem]], str]:
    if quality_service is None or not actor.has_capability("ops.quality.read"):
        return [], "ok"
    try:
        cases = quality_service.list_cases(actor=actor, owner_unit_id=owner_unit_id)
        results = [_build_quality_case_work_item(case) for case in cases]
        return results, "ok"
    except Exception as err:
        logger.warning("Failed to collect quality work items: %s", err, exc_info=True)
        return [], "unavailable"


def _collect_knowledge_items(
    knowledge_client: Any,
    actor: ActorContext,
) -> tuple[list[tuple[str, WorkItem]], str]:
    if knowledge_client is None or not getattr(knowledge_client, "configured", False):
        return [], "ok"
    if not (actor.has_capability("knowledge.review") or actor.has_capability("knowledge.review.ui")):
        return [], "ok"
    return [], "ok"


def register_console_routes(
    app: FastAPI,
    *,
    quality_service: Any = None,
    knowledge_client: Any = None,
    evaluation_service: Any = None,
    evaluation_run_service: Any = None,
    quality_gate_service: Any = None,
    current_actor: Any,
    require_capability: Any,
) -> None:
    @app.get("/api/console/work-items", response_model=WorkItemsResponse)
    async def list_work_items(
        bucket: str = Query(default="all"),
        workflow: str | None = Query(default=None),
        owner_unit_id: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=25, ge=1, le=100),
        actor: ActorContext = Depends(current_actor),
    ) -> WorkItemsResponse:
        target_bucket = bucket.strip().lower()
        if target_bucket not in VALID_BUCKETS:
            raise HTTPException(status_code=400, detail=f"Invalid bucket: {bucket}")

        q_items, q_source = _collect_quality_items(quality_service, actor, owner_unit_id)
        k_items, k_source = _collect_knowledge_items(knowledge_client, actor)

        sources = {
            "quality_case": q_source,
            "knowledge_review": k_source,
        }

        all_collected = q_items + k_items
        filtered_items: list[WorkItem] = []
        for item_bucket, item in all_collected:
            if target_bucket != "all" and item_bucket != target_bucket:
                continue
            if workflow and item.workflow != workflow:
                continue
            filtered_items.append(item)

        filtered_items.sort(key=lambda x: (x.updated_at, x.key), reverse=True)

        snapshot_basis = f"{len(filtered_items)}:{datetime.now(UTC).strftime('%Y%m%d%H')}"
        snapshot_id = hashlib.sha256(snapshot_basis.encode()).hexdigest()[:16]

        offset = _decode_cursor(cursor, actor.user_id) if cursor else 0
        paged_items = filtered_items[offset : offset + limit]
        has_next = (offset + limit) < len(filtered_items)
        next_cursor = _encode_cursor(offset + limit, actor.user_id, snapshot_id) if has_next else None

        return WorkItemsResponse(
            items=paged_items,
            next_cursor=next_cursor,
            total=len(filtered_items),
            snapshot_id=snapshot_id,
            generated_at=datetime.now(UTC).isoformat(),
            partial=any(v == "unavailable" for v in sources.values()),
            sources=sources,
        )

    @app.get("/api/console/work-summary", response_model=WorkSummaryResponse)
    async def get_work_summary(
        owner_unit_id: str | None = Query(default=None),
        actor: ActorContext = Depends(current_actor),
    ) -> WorkSummaryResponse:
        q_items, q_source = _collect_quality_items(quality_service, actor, owner_unit_id)
        k_items, k_source = _collect_knowledge_items(knowledge_client, actor)

        sources = {
            "quality_case": q_source,
            "knowledge_review": k_source,
        }

        all_collected = q_items + k_items
        by_bucket = {
            "pending_action": 0,
            "pending_review": 0,
            "tracking": 0,
            "completed": 0,
        }
        by_workflow: dict[str, int] = {
            "quality_improvement": 0,
            "knowledge_review": 0,
            "eval_gate": 0,
        }

        for item_bucket, item in all_collected:
            if item_bucket in by_bucket:
                by_bucket[item_bucket] += 1
            by_workflow[item.workflow] = by_workflow.get(item.workflow, 0) + 1

        snapshot_basis = f"{len(all_collected)}:{datetime.now(UTC).strftime('%Y%m%d%H')}"
        snapshot_id = hashlib.sha256(snapshot_basis.encode()).hexdigest()[:16]

        return WorkSummaryResponse(
            total=len(all_collected),
            by_bucket=by_bucket,
            by_workflow=by_workflow,
            sources=sources,
            snapshot_id=snapshot_id,
            generated_at=datetime.now(UTC).isoformat(),
        )

    @app.get("/api/console/workflows/{kind}/{item_id}", response_model=WorkflowDetailResponse)
    async def get_workflow_detail(
        kind: str,
        item_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> WorkflowDetailResponse:
        if kind not in WORKFLOW_KINDS:
            raise HTTPException(status_code=404, detail=f"Unknown workflow kind: {kind}")

        if kind == "quality_case":
            require_capability(actor, "ops.quality.read")
            if quality_service is None:
                raise HTTPException(status_code=503, detail="Quality service unavailable")

            detail = quality_service.case_detail(item_id, actor=actor)
            case = detail["case"]
            status = str(case.get("status", "NEW")).upper()

            stages = [
                WorkflowStage(
                    id="triage",
                    title="分流與確認",
                    status="completed" if status != "NEW" else "current",
                ),
                WorkflowStage(
                    id="fix_content",
                    title="內容修正",
                    status=(
                        "completed"
                        if status in {"WAITING_REVIEW", "OBSERVING", "RESOLVED"}
                        else ("current" if status == "IN_PROGRESS" else "pending")
                    ),
                ),
                WorkflowStage(
                    id="verification_review",
                    title="審核驗證",
                    status=(
                        "completed"
                        if status in {"OBSERVING", "RESOLVED"}
                        else ("current" if status == "WAITING_REVIEW" else "pending")
                    ),
                ),
                WorkflowStage(
                    id="observation",
                    title="上線觀察",
                    status=(
                        "completed"
                        if status == "RESOLVED"
                        else ("current" if status == "OBSERVING" else "pending")
                    ),
                ),
                WorkflowStage(
                    id="resolution",
                    title="結案驗收",
                    status="completed" if status in {"RESOLVED", "WONT_FIX", "DUPLICATE"} else "pending",
                ),
            ]

            now_iso = datetime.now(UTC).isoformat()
            evidence_refs: list[EvidenceRef] = []

            for doc_id in case.get("document_ids", ()):
                evidence_refs.append(
                    EvidenceRef(
                        source_type="document_draft",
                        source_id=doc_id,
                        relation="fix_target",
                        retrieved_at=now_iso,
                        validity="valid",
                    )
                )

            for faq_id in case.get("faq_ids", ()):
                evidence_refs.append(
                    EvidenceRef(
                        source_type="faq_draft",
                        source_id=faq_id,
                        relation="fix_target",
                        retrieved_at=now_iso,
                        validity="valid",
                    )
                )

            for cand_id in case.get("source_candidate_ids", ()):
                evidence_refs.append(
                    EvidenceRef(
                        source_type="quality_candidate",
                        source_id=cand_id,
                        relation="source_issue",
                        retrieved_at=now_iso,
                        validity="valid",
                    )
                )

            if case.get("observation_latest"):
                evidence_refs.append(
                    EvidenceRef(
                        source_type="observation_metric",
                        source_id=f"{item_id}:latest",
                        relation="observation_result",
                        occurred_at=case.get("observation_started_at"),
                        retrieved_at=now_iso,
                        validity="valid",
                    )
                )

            action_map = {
                "NEW": ["triage", "close_wont_fix", "close_duplicate"],
                "TRIAGED": [
                    "start_progress",
                    "create_document_draft",
                    "create_faq_draft",
                    "link_content",
                    "close_wont_fix",
                    "close_duplicate",
                ],
                "IN_PROGRESS": [
                    "create_document_draft",
                    "create_faq_draft",
                    "link_content",
                    "request_review",
                    "close_wont_fix",
                ],
                "WAITING_REVIEW": ["start_observation", "reject_review"],
                "OBSERVING": ["refresh_observation", "resolve", "rollback"],
                "RESOLVED": ["reopen"],
                "WONT_FIX": ["reopen"],
                "DUPLICATE": ["reopen"],
            }
            allowed_actions = action_map.get(status, ["view"])

            return WorkflowDetailResponse(
                kind=kind,
                id=item_id,
                title=str(case.get("title", "")),
                status=status,
                stages=stages,
                evidence_refs=evidence_refs,
                allowed_actions=allowed_actions,
                return_route="/console-v2/work",
            )

        raise HTTPException(status_code=501, detail=f"Workflow kind {kind} not implemented yet")
