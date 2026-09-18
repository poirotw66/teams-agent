"""FAQ list, detail, and performance read routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, FastAPI

from .context import FaqRouteContext
from .filters import filter_faq_items


def register_faq_read_routes(app: FastAPI, ctx: FaqRouteContext) -> None:
    faq_service = ctx.faq_service
    query_service = ctx.query_service
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability

    @app.get("/api/faqs")
    async def list_faqs(
        status: str | None = None,
        owner_unit_id: str | None = None,
        category: str | None = None,
        keyword: str | None = None,
        query: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.read")
        items = filter_faq_items(
            faq_service.list_faqs(actor=actor),
            status=status,
            owner_unit_id=owner_unit_id,
            category=category,
            keyword=keyword,
            query=query,
        )
        return {"items": items, "total": len(items)}

    @app.get("/api/faqs/{faq_id}")
    async def get_faq(faq_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.faq.read")
        return faq_service.detail(faq_id=faq_id, actor=actor)

    @app.get("/api/faqs/{faq_id}/performance")
    async def get_faq_performance(
        faq_id: str,
        days: int | None = None,
        preset: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        as_of: datetime | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.faq.read")
        detail = faq_service.detail(faq_id=faq_id, actor=actor)
        faq_key = detail["faq"]["faq_key"]
        return await query_service.faq_performance(
            actor,
            faq_key=faq_key,
            faq_id=faq_id,
            days=days,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            as_of=as_of,
        )
