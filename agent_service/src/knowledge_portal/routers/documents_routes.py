"""Knowledge Portal documents HTTP routes (orchestrator)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException

from knowledge_portal.models import PortalActor
from knowledge_portal.routers.documents_chunk_routes import register_documents_chunk_routes
from knowledge_portal.routers.documents_crud_routes import register_documents_crud_routes
from knowledge_portal.routers.documents_publish_routes import register_documents_publish_routes
from knowledge_portal.routers.documents_removal_routes import register_documents_removal_routes
from knowledge_portal.routers.documents_review_prep_routes import (
    register_documents_review_prep_routes,
)
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_documents_routes(
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
    register_documents_crud_routes(app, **kwargs)
    register_documents_removal_routes(app, **kwargs)
    register_documents_chunk_routes(app, **kwargs)
    register_documents_review_prep_routes(app, **kwargs)
    register_documents_publish_routes(app, **kwargs)
