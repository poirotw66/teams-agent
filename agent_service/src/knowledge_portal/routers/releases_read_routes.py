"""Knowledge Portal release read HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_releases_read_routes(
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
    del settings, pdf_job_store, correlation_id, idempotency_key

    @app.get("/api/releases")
    async def list_releases(
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.list_releases(actor)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/releases/compare")
    async def compare_releases(
        target_release_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.compare_releases(
                actor, target_release_id=target_release_id
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/audit-events")
    async def list_audit(
        limit: int = 100,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.list_audit(actor, limit=limit)
        except Exception as exc:
            raise handle_errors(exc) from exc
