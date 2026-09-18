"""Knowledge Portal admin bootstrap HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
)

from knowledge_portal.models import (
    BootstrapReleaseRequest,
    PortalActor,
)
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_admin_routes(
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
    @app.post("/api/admin/bootstrap-release-0001")
    async def bootstrap_release_0001(
        request: BootstrapReleaseRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        sources_dir = (
            Path(request.sources_dir)
            if request.sources_dir
            else (settings.data_dir / "sources")
        )
        if not sources_dir.exists():
            sources_dir = settings.data_dir / "sources.sample"
        try:
            return await service.bootstrap_release_0001(
                actor,
                sources_dir,
                correlation_id_value,
                release_id=request.release_id,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

