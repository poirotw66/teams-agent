"""Entra ID token tenant and issuer validation helpers."""

from __future__ import annotations

from collections.abc import Collection

from fastapi import HTTPException


def validate_token_tenant_and_issuer(
    *,
    token_iss: str,
    token_tid: str,
    tenant_id: str,
    allowed_tenants: Collection[str] | None,
) -> None:
    is_single_tenant = bool(
        tenant_id and tenant_id not in ("common", "organizations", "consumers")
    )
    if is_single_tenant:
        allowed_issuers = {
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://sts.windows.net/{tenant_id}/",
        }
        if token_iss not in allowed_issuers:
            raise HTTPException(
                status_code=401, detail=f"ID token issuer mismatch: {token_iss}"
            )
        if token_tid and token_tid != tenant_id:
            raise HTTPException(
                status_code=401,
                detail=f"ID token tenant mismatch: expected {tenant_id}, got {token_tid}.",
            )
        return

    if allowed_tenants is not None:
        allowed_set = {str(t).strip() for t in allowed_tenants if str(t).strip()}
        if token_tid and token_tid not in allowed_set:
            raise HTTPException(
                status_code=401,
                detail=f"ID token tenant {token_tid} is not in allowed tenants.",
            )
        allowed_issuers = {
            f"https://login.microsoftonline.com/{t}/v2.0" for t in allowed_set
        } | {f"https://sts.windows.net/{t}/" for t in allowed_set}
        if token_iss not in allowed_issuers:
            raise HTTPException(
                status_code=401, detail=f"ID token issuer mismatch: {token_iss}"
            )
        return

    if not token_tid:
        raise HTTPException(status_code=401, detail="ID token missing tid claim.")
    allowed_issuers = {
        f"https://login.microsoftonline.com/{token_tid}/v2.0",
        f"https://sts.windows.net/{token_tid}/",
    }
    if token_iss not in allowed_issuers:
        raise HTTPException(
            status_code=401, detail=f"ID token issuer mismatch: {token_iss}"
        )
