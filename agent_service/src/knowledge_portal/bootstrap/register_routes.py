"""Register Knowledge Portal HTTP routes on a FastAPI app."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException

from knowledge_portal.models import PortalActor
from knowledge_portal.routers import (
    register_admin_routes,
    register_catalog_routes,
    register_documents_assets_routes,
    register_documents_import_routes,
    register_documents_routes,
    register_health_routes,
    register_releases_routes,
    register_reviews_routes,
    register_tests_routes,
)
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_portal_routes(
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
    kwargs = dict(
        settings=settings,
        service=service,
        pdf_job_store=pdf_job_store,
        authorize=authorize,
        current_actor=current_actor,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        handle_errors=handle_errors,
    )
    register_health_routes(app, **kwargs)
    register_documents_import_routes(app, **kwargs)
    register_documents_assets_routes(app, **kwargs)
    register_documents_routes(app, **kwargs)
    register_catalog_routes(app, **kwargs)
    register_reviews_routes(app, **kwargs)
    register_releases_routes(app, **kwargs)
    register_tests_routes(app, **kwargs)
    register_admin_routes(app, **kwargs)
