"""Knowledge Portal review workflow HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
)

from knowledge_portal.models import (
    PortalActor,
    ReviewDecisionRequest,
)
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_reviews_routes(
    app: FastAPI,
    *,
    settings: PortalSettings,
    service: PortalService,
    pdf_job_store: Any,
    authorize: Callable[..., None],
    current_actor: Callable[..., PortalActor],
    correlation_id: Callable[..., str],
    idempotency_key: Callable[..., str | None],
    handle_errors: Callable[[Exception], HTTPException],
) -> None:
    @app.get("/api/reviews/pending")
    async def list_pending_reviews(
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.list_pending_reviews(actor)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/reviews/{review_id}/decision")
    async def review_decision(
        review_id: str,
        request: ReviewDecisionRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.decide_review(actor, review_id, request, correlation_id_value)
        except Exception as exc:
            raise handle_errors(exc) from exc

