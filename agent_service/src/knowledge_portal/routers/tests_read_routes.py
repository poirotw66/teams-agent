"""Knowledge Portal draft test read HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_portal.models import PortalActor
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_tests_read_routes(
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

    @app.get("/api/documents/{document_id}/test-cases")
    async def list_test_cases(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.list_test_cases(actor, document_id)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/documents/{document_id}/test-runs")
    async def list_test_runs(
        document_id: str,
        test_case_id: str | None = None,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.list_test_runs(
                actor, document_id, test_case_id=test_case_id
            )
        except Exception as exc:
            raise handle_errors(exc) from exc
