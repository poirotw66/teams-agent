"""Knowledge Portal sync reindex HTTP route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_releases_sync_route(
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
    del settings, pdf_job_store, idempotency_key

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
