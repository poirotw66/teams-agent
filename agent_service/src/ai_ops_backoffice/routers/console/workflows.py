"""Console workflow detail routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from agent_service.operations.access import ActorContext

from .constants import WORKFLOW_KINDS
from .context import ConsoleRouteContext
from .models import EvidenceRef, WorkflowDetailResponse, WorkflowStage

_ALLOWED_ACTIONS: dict[str, list[str]] = {
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


def _stage_status(
    *,
    completed_when: bool,
    current_when: bool,
) -> str:
    if completed_when:
        return "completed"
    if current_when:
        return "current"
    return "pending"


def build_quality_case_stages(status: str) -> list[WorkflowStage]:
    return [
        WorkflowStage(
            id="triage",
            title="分流與確認",
            status="completed" if status != "NEW" else "current",
        ),
        WorkflowStage(
            id="fix_content",
            title="內容修正",
            status=_stage_status(
                completed_when=status in {"WAITING_REVIEW", "OBSERVING", "RESOLVED"},
                current_when=status == "IN_PROGRESS",
            ),
        ),
        WorkflowStage(
            id="verification_review",
            title="審核驗證",
            status=_stage_status(
                completed_when=status in {"OBSERVING", "RESOLVED"},
                current_when=status == "WAITING_REVIEW",
            ),
        ),
        WorkflowStage(
            id="observation",
            title="上線觀察",
            status=_stage_status(
                completed_when=status == "RESOLVED",
                current_when=status == "OBSERVING",
            ),
        ),
        WorkflowStage(
            id="resolution",
            title="結案驗收",
            status="completed" if status in {"RESOLVED", "WONT_FIX", "DUPLICATE"} else "pending",
        ),
    ]


def build_quality_case_evidence_refs(
    case: dict[str, Any],
    *,
    item_id: str,
    now_iso: str,
) -> list[EvidenceRef]:
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
    return evidence_refs


def register_workflow_routes(app: FastAPI, ctx: ConsoleRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    quality_service = ctx.quality_service

    @app.get("/api/console/workflows/{kind}/{item_id}", response_model=WorkflowDetailResponse)
    async def get_workflow_detail(
        kind: str,
        item_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> WorkflowDetailResponse:
        if kind not in WORKFLOW_KINDS:
            raise HTTPException(status_code=404, detail=f"Unknown workflow kind: {kind}")

        if kind != "quality_case":
            raise HTTPException(status_code=501, detail=f"Workflow kind {kind} not implemented yet")

        require_capability(actor, "ops.quality.read")
        if quality_service is None:
            raise HTTPException(status_code=503, detail="Quality service unavailable")

        detail = quality_service.case_detail(item_id, actor=actor)
        case = detail["case"]
        status = str(case.get("status", "NEW")).upper()
        now_iso = datetime.now(UTC).isoformat()

        return WorkflowDetailResponse(
            kind=kind,
            id=item_id,
            title=str(case.get("title", "")),
            status=status,
            stages=build_quality_case_stages(status),
            evidence_refs=build_quality_case_evidence_refs(
                case, item_id=item_id, now_iso=now_iso
            ),
            allowed_actions=_ALLOWED_ACTIONS.get(status, ["view"]),
            return_route="/console-v2/work",
        )
