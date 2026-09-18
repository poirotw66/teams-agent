"""Build Knowledge Portal runtime collaborators for create_app."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException, Request

from knowledge_portal.auth import PortalAuthError, resolve_portal_actor
from knowledge_portal.models import PortalActor
from knowledge_portal.persistent_pdf_jobs import build_pdf_convert_job_store
from knowledge_portal.repository import build_repository
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings

from .error_handlers import portal_http_exception


@dataclass(frozen=True)
class PortalContainer:
    settings: PortalSettings
    service: PortalService
    pdf_job_store: Any
    authorize: Callable[..., None]
    current_actor: Callable[..., PortalActor]
    correlation_id: Callable[..., str]
    idempotency_key: Callable[..., str | None]
    handle_errors: Callable[[Exception], HTTPException]


def build_portal_container(
    settings: PortalSettings,
    *,
    release_gate_checker: object | None = None,
    source_catalog_writer: object | None = None,
) -> PortalContainer:
    repository = build_repository(settings)
    service = PortalService(
        settings,
        repository,
        release_gate_checker=release_gate_checker,
        source_catalog_writer=source_catalog_writer,
    )
    pdf_job_store = build_pdf_convert_job_store(settings)
    return PortalContainer(
        settings=settings,
        service=service,
        pdf_job_store=pdf_job_store,
        authorize=_build_authorize(settings),
        current_actor=_build_current_actor(settings),
        correlation_id=_build_correlation_id(),
        idempotency_key=_build_idempotency_key(),
        handle_errors=portal_http_exception,
    )


def _build_authorize(settings: PortalSettings) -> Callable[..., None]:
    def authorize(
        authorization: str | None = Header(default=None),
        x_knowledge_delegation: str | None = Header(
            default=None, alias="X-Knowledge-Delegation"
        ),
    ) -> None:
        if x_knowledge_delegation and not settings.require_service_token_with_delegation:
            return
        expected = settings.service_token
        if not expected:
            return
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid service token.")

    return authorize


def _build_current_actor(settings: PortalSettings) -> Callable[..., PortalActor]:
    def current_actor(
        authorization: str | None = Header(default=None),
        x_portal_user_id: str | None = Header(default=None, alias="X-Portal-User-Id"),
        x_portal_user_name: str | None = Header(default=None, alias="X-Portal-User-Name"),
        x_portal_role: str | None = Header(default="CONTRIBUTOR", alias="X-Portal-Role"),
        x_portal_owner_units: str | None = Header(default="", alias="X-Portal-Owner-Units"),
        x_knowledge_delegation: str | None = Header(
            default=None, alias="X-Knowledge-Delegation"
        ),
    ) -> PortalActor:
        try:
            return resolve_portal_actor(
                settings=settings,
                authorization=authorization,
                header_user_id=x_portal_user_id,
                header_user_name=x_portal_user_name,
                header_role=x_portal_role,
                header_owner_units=x_portal_owner_units,
                delegation_header=x_knowledge_delegation,
            )
        except PortalAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    return current_actor


def _build_correlation_id() -> Callable[..., str]:
    def correlation_id(request: Request) -> str:
        return request.headers.get("X-Correlation-Id") or uuid.uuid4().hex

    return correlation_id


def _build_idempotency_key() -> Callable[..., str | None]:
    def idempotency_key(request: Request) -> str | None:
        return request.headers.get("idempotency-key") or request.headers.get(
            "x-idempotency-key"
        )

    return idempotency_key
