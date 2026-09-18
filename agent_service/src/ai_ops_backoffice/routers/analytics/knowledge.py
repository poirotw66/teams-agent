"""Knowledge document list and performance routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query

from .context import AnalyticsRouteContext


def register_knowledge_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service
    audit_read = ctx.audit_read

    @app.get("/api/knowledge")
    async def knowledge_documents(
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
        format_type: str | None = None,
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.knowledge.read")
        result = await query_service.list_documents(
            actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
            format_type=format_type,
            preset=preset,
            days=days,
            limit=limit,
            cursor=cursor,
        )
        await audit_read(
            actor,
            "knowledge.documents.list",
            "knowledge_documents",
            after={
                "status": status,
                "ownerUnitId": owner_unit_id,
                "formatType": format_type,
                "resultCount": len(result["items"]),
            },
        )
        return result

    @app.get("/api/knowledge/{document_id}/performance")
    async def knowledge_performance(
        document_id: str,
        days: int = Query(default=30, ge=1, le=365),
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        cursor: str | None = None,
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.knowledge.read")
        return await query_service.document_performance(
            actor,
            document_id,
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
            issue_type_id=issue_type_id,
            limit=limit,
            cursor=cursor,
        )
