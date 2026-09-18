"""Console work-items and work-summary routes."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Query

from agent_service.operations.access import ActorContext

from .collection import (
    collect_knowledge_items,
    collect_quality_items,
    decode_cursor,
    encode_cursor,
)
from .constants import VALID_BUCKETS
from .context import ConsoleRouteContext
from .models import WorkItem, WorkItemsResponse, WorkSummaryResponse


def _list_work_items(
    *,
    bucket: str,
    workflow: str | None,
    owner_unit_id: str | None,
    cursor: str | None,
    limit: int,
    actor: ActorContext,
    quality_service,
    knowledge_client,
) -> WorkItemsResponse:
    target_bucket = bucket.strip().lower()
    if target_bucket not in VALID_BUCKETS:
        raise HTTPException(status_code=400, detail=f"Invalid bucket: {bucket}")

    q_items, q_source = collect_quality_items(quality_service, actor, owner_unit_id)
    k_items, k_source = collect_knowledge_items(knowledge_client, actor)
    sources = {"quality_case": q_source, "knowledge_review": k_source}

    filtered_items: list[WorkItem] = []
    for item_bucket, item in q_items + k_items:
        if target_bucket != "all" and item_bucket != target_bucket:
            continue
        if workflow and item.workflow != workflow:
            continue
        filtered_items.append(item)

    filtered_items.sort(key=lambda x: (x.updated_at, x.key), reverse=True)
    snapshot_basis = f"{len(filtered_items)}:{datetime.now(UTC).strftime('%Y%m%d%H')}"
    snapshot_id = hashlib.sha256(snapshot_basis.encode()).hexdigest()[:16]
    offset = decode_cursor(cursor, actor.user_id) if cursor else 0
    paged_items = filtered_items[offset : offset + limit]
    has_next = (offset + limit) < len(filtered_items)
    next_cursor = encode_cursor(offset + limit, actor.user_id, snapshot_id) if has_next else None

    return WorkItemsResponse(
        items=paged_items,
        next_cursor=next_cursor,
        total=len(filtered_items),
        snapshot_id=snapshot_id,
        generated_at=datetime.now(UTC).isoformat(),
        partial=any(v == "unavailable" for v in sources.values()),
        sources=sources,
    )


def _get_work_summary(
    *,
    owner_unit_id: str | None,
    actor: ActorContext,
    quality_service,
    knowledge_client,
) -> WorkSummaryResponse:
    q_items, q_source = collect_quality_items(quality_service, actor, owner_unit_id)
    k_items, k_source = collect_knowledge_items(knowledge_client, actor)
    sources = {"quality_case": q_source, "knowledge_review": k_source}
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


def register_work_item_routes(app: FastAPI, ctx: ConsoleRouteContext) -> None:
    current_actor = ctx.current_actor
    quality_service = ctx.quality_service
    knowledge_client = ctx.knowledge_client

    @app.get("/api/console/work-items", response_model=WorkItemsResponse)
    async def list_work_items(
        bucket: str = Query(default="all"),
        workflow: str | None = Query(default=None),
        owner_unit_id: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=25, ge=1, le=100),
        actor: ActorContext = Depends(current_actor),
    ) -> WorkItemsResponse:
        return _list_work_items(
            bucket=bucket,
            workflow=workflow,
            owner_unit_id=owner_unit_id,
            cursor=cursor,
            limit=limit,
            actor=actor,
            quality_service=quality_service,
            knowledge_client=knowledge_client,
        )

    @app.get("/api/console/work-summary", response_model=WorkSummaryResponse)
    async def get_work_summary(
        owner_unit_id: str | None = Query(default=None),
        actor: ActorContext = Depends(current_actor),
    ) -> WorkSummaryResponse:
        return _get_work_summary(
            owner_unit_id=owner_unit_id,
            actor=actor,
            quality_service=quality_service,
            knowledge_client=knowledge_client,
        )
