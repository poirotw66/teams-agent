"""Knowledge Portal release mutation HTTP routes (rollback / promote / sync-agent)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_portal.models import PortalActor, RollbackRequest
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_releases_mutation_routes(
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
    del settings, pdf_job_store

    @app.post("/api/releases/rollback")
    async def rollback_release(
        request: RollbackRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
        idempotency_key_value: str | None = Depends(idempotency_key),
    ):
        try:
            return await service.rollback_release(
                actor,
                request,
                correlation_id_value,
                idempotency_key=idempotency_key_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/releases/{release_id}/promote")
    async def promote_candidate_release(
        release_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.promote_candidate_release(
                actor,
                release_id,
                correlation_id=correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/releases/{release_id}/sync-agent")
    async def sync_agent_release(
        release_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.sync_agent_release(
                actor, release_id, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc
