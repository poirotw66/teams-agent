"""Knowledge Portal FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from knowledge_portal.bootstrap.container import build_portal_container
from knowledge_portal.bootstrap.register_routes import register_portal_routes
from knowledge_portal.settings import PortalSettings

__all__ = ["app", "create_app"]


def create_app(
    settings: PortalSettings | None = None,
    *,
    release_gate_checker: object | None = None,
    source_catalog_writer: object | None = None,
) -> FastAPI:
    resolved_settings = settings or PortalSettings.from_env()
    # Composition root (composition.portal_app / Backoffice bootstrap) injects
    # release-gate and source-catalog adapters. Domain create_app stays free of
    # Backoffice imports.
    container = build_portal_container(
        resolved_settings,
        release_gate_checker=release_gate_checker,
        source_catalog_writer=source_catalog_writer,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.release_artifact_dir.mkdir(parents=True, exist_ok=True)
        resolved_settings.drafts_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(
        title="Knowledge Operations Portal API",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_portal_routes(
        app,
        settings=container.settings,
        service=container.service,
        pdf_job_store=container.pdf_job_store,
        authorize=container.authorize,
        current_actor=container.current_actor,
        correlation_id=container.correlation_id,
        idempotency_key=container.idempotency_key,
        handle_errors=container.handle_errors,
    )
    return app


app = create_app()
