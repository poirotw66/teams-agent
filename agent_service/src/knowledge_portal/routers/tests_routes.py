"""Knowledge Portal draft tests and search HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException

from knowledge_portal.models import PortalActor
from knowledge_portal.routers.tests_read_routes import register_tests_read_routes
from knowledge_portal.routers.tests_write_routes import register_tests_write_routes
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_tests_routes(
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
    register_tests_read_routes(app, **kwargs)
    register_tests_write_routes(app, **kwargs)
