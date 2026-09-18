"""Knowledge Portal health and shell HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from knowledge_portal.models import (
    PortalActor,
)
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

def register_health_routes(
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
    async def disable_portal_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/healthz")
    @app.get("/health")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def portal_home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/dashboard")
    async def dashboard(
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        return await service.dashboard(actor)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
