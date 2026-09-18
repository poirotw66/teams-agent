"""Actor resolution dependency factory for Backoffice routes."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from fastapi import Header, HTTPException

from operations_core.access import ActorContext

from .auth import BackofficeAuthError, resolve_actor
from .settings import BackofficeSettings


def build_current_actor_dependency(
    *,
    resolved_settings: BackofficeSettings,
    query_service: Any,
) -> Callable[..., ActorContext]:
    def current_actor(
        authorization: str | None = Header(default=None),
        x_backoffice_user_id: str | None = Header(default=None, alias="X-Backoffice-User-Id"),
        x_backoffice_user_name: str | None = Header(default=None, alias="X-Backoffice-User-Name"),
        x_backoffice_role: str | None = Header(default="ANALYST", alias="X-Backoffice-Role"),
        x_backoffice_owner_units: str | None = Header(default="", alias="X-Backoffice-Owner-Units"),
        x_backoffice_tenant_id: str | None = Header(default=None, alias="X-Backoffice-Tenant-Id"),
        x_backoffice_groups: str | None = Header(default="", alias="X-Backoffice-Groups"),
        x_backoffice_revoked: str | None = Header(default="false", alias="X-Backoffice-Revoked"),
        x_source_delegation: str | None = Header(default=None, alias="X-Source-Delegation"),
        x_backoffice_service_token: str | None = Header(
            default=None, alias="X-Backoffice-Service-Token"
        ),
    ) -> ActorContext:
        if x_source_delegation:
            actor = _actor_from_source_delegation(
                resolved_settings=resolved_settings,
                authorization=authorization,
                x_backoffice_service_token=x_backoffice_service_token,
                x_source_delegation=x_source_delegation,
            )
        else:
            actor = _actor_from_headers(
                resolved_settings=resolved_settings,
                authorization=authorization,
                x_backoffice_user_id=x_backoffice_user_id,
                x_backoffice_user_name=x_backoffice_user_name,
                x_backoffice_role=x_backoffice_role,
                x_backoffice_owner_units=x_backoffice_owner_units,
                x_backoffice_tenant_id=x_backoffice_tenant_id,
                x_backoffice_groups=x_backoffice_groups,
                x_backoffice_revoked=x_backoffice_revoked,
            )
        revoked_checker = getattr(query_service, "is_principal_revoked", None)
        if callable(revoked_checker) and revoked_checker(actor.user_id, actor.tenant_id):
            actor = replace(actor, revoked=True)
        return actor

    return current_actor


def _actor_from_source_delegation(
    *,
    resolved_settings: BackofficeSettings,
    authorization: str | None,
    x_backoffice_service_token: str | None,
    x_source_delegation: str,
) -> ActorContext:
    expected = resolved_settings.service_token
    if not expected:
        raise HTTPException(
            status_code=401,
            detail="Service token is required for source delegation.",
        )
    scheme, _, token = (authorization or "").partition(" ")
    bearer_ok = scheme.lower() == "bearer" and bool(token) and hmac.compare_digest(token, expected)
    header_ok = bool(x_backoffice_service_token) and hmac.compare_digest(
        x_backoffice_service_token, expected
    )
    # Cloud Run private invoke uses Authorization for the Google ID
    # token; Adapter then sends the shared service token in
    # X-Backoffice-Service-Token.
    if not (bearer_ok or header_ok):
        raise HTTPException(status_code=401, detail="Invalid service token.")
    secret = resolved_settings.source_delegation_secret or resolved_settings.service_token
    try:
        from .source_delegation import (
            SourceDelegationError,
            actor_from_source_delegation,
            verify_source_delegation,
        )

        payload = verify_source_delegation(x_source_delegation, secret=secret)
        return actor_from_source_delegation(payload)
    except SourceDelegationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _actor_from_headers(
    *,
    resolved_settings: BackofficeSettings,
    authorization: str | None,
    x_backoffice_user_id: str | None,
    x_backoffice_user_name: str | None,
    x_backoffice_role: str | None,
    x_backoffice_owner_units: str | None,
    x_backoffice_tenant_id: str | None,
    x_backoffice_groups: str | None,
    x_backoffice_revoked: str | None,
) -> ActorContext:
    try:
        return resolve_actor(
            auth_mode=resolved_settings.auth_mode,
            authorization=authorization,
            header_user_id=x_backoffice_user_id,
            header_user_name=x_backoffice_user_name,
            header_role=x_backoffice_role,
            header_owner_units=x_backoffice_owner_units,
            header_tenant_id=x_backoffice_tenant_id,
            header_groups=x_backoffice_groups,
            revoked=(x_backoffice_revoked or "").lower() in {"1", "true", "yes", "on"},
            default_owner_unit_id=resolved_settings.default_owner_unit_id,
            entra_tenant_id=resolved_settings.entra_tenant_id,
            entra_client_id=resolved_settings.entra_client_id,
        )
    except BackofficeAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
