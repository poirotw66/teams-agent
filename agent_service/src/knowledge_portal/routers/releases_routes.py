"""Knowledge Portal releases and sync HTTP routes."""

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
    RollbackRequest,
)
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_releases_routes(
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
            return await service.sync_agent_release(actor, release_id, correlation_id_value)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/sync")
    async def sync_knowledge(
        payload: dict[str, Any] | None = None,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ) -> dict[str, Any]:
        try:
            scope_type = (payload or {}).get("scopeType") or "ALL"
            scope_ids = list((payload or {}).get("scopeIds") or [])
            corr = (payload or {}).get("correlationId") or correlation_id_value
            release = await service.reindex_all_published(
                actor,
                scope_type=scope_type,
                scope_ids=scope_ids,
                correlation_id=corr,
                reason="Backoffice sync job triggered reindex",
                embedding_model=(payload or {}).get("embeddingModel") or None,
            )
            return {
                "targetRelease": release.release_id,
                "indexSettingVersion": "v1",
                "documentCount": len(release.manifest),
                "warnings": [release.failure_summary] if release.failure_summary else [],
            }
        except Exception as exc:
            raise handle_errors(exc) from exc

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
            return await service.compare_releases(actor, target_release_id=target_release_id)
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

