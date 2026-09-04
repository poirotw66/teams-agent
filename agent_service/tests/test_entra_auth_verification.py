"""Tests for Item 1: Real Entra RS256 signature verification, JWKS key rotation, and 401 error conversion."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.auth import BackofficeAuthError, resolve_actor
from ai_ops_backoffice.entra_auth import (
    EntraAuthError,
    resolve_actor_from_entra,
)


def _generate_rsa_key_and_jwk(kid: str) -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return private_key, jwk


def test_entra_auth_valid_rs256_token() -> None:
    priv_key, jwk = _generate_rsa_key_and_jwk("kid-2026-01")
    jwks = {"keys": [jwk]}

    payload = {
        "sub": "user-oid-001",
        "name": "Alex Admin",
        "roles": ["AI_OPS_SYSTEM_ADMIN"],
        "aud": "client-app-id-123",
        "iss": "https://login.microsoftonline.com/tenant-abc/v2.0",
        "exp": int(time.time()) + 3600,
        "nbf": int(time.time()) - 10,
        "tid": "tenant-abc",
    }
    token = jwt.encode(payload, priv_key, algorithm="RS256", headers={"kid": "kid-2026-01"})

    actor = resolve_actor_from_entra(
        token,
        tenant_id="tenant-abc",
        client_id="client-app-id-123",
        default_owner_unit_id="IT Service Desk",
        validate_signature=True,
        jwks=jwks,
    )

    assert isinstance(actor, ActorContext)
    assert actor.user_id == "user-oid-001"
    assert actor.display_name == "Alex Admin"
    assert actor.role == "SYSTEM_ADMIN"
    assert actor.tenant_id == "tenant-abc"


def test_entra_auth_v1_issuer_supported() -> None:
    priv_key, jwk = _generate_rsa_key_and_jwk("kid-v1")
    jwks = {"keys": [jwk]}

    payload = {
        "oid": "user-oid-v1",
        "name": "V1 User",
        "groups": ["AI_OPS_KNOWLEDGE_ADMIN"],
        "extension_owner_units": "Finance, Accounting",
        "aud": "client-app-id-123",
        "iss": "https://sts.windows.net/tenant-abc/",
        "exp": int(time.time()) + 3600,
        "tid": "tenant-abc",
    }
    token = jwt.encode(payload, priv_key, algorithm="RS256", headers={"kid": "kid-v1"})

    actor = resolve_actor_from_entra(
        token,
        tenant_id="tenant-abc",
        client_id="client-app-id-123",
        default_owner_unit_id="IT Service Desk",
        validate_signature=True,
        jwks=jwks,
    )

    assert actor.user_id == "user-oid-v1"
    assert actor.role == "KNOWLEDGE_ADMIN"
    assert actor.owner_unit_ids == ("Finance", "Accounting")


def test_entra_auth_key_rotation_matches_new_key() -> None:
    _priv_old, jwk_old = _generate_rsa_key_and_jwk("kid-old-2025")
    priv_new, jwk_new = _generate_rsa_key_and_jwk("kid-new-2026")
    # JWKS holds both the retired and the newly rotated key
    jwks = {"keys": [jwk_old, jwk_new]}

    payload = {
        "sub": "user-kadmin",
        "roles": ["AI_OPS_KNOWLEDGE_ADMIN"],
        "aud": "client-123",
        "iss": "https://login.microsoftonline.com/tenant-123/v2.0",
        "exp": int(time.time()) + 3600,
    }
    # Token minted using the NEW rotated private key
    token = jwt.encode(payload, priv_new, algorithm="RS256", headers={"kid": "kid-new-2026"})

    actor = resolve_actor_from_entra(
        token,
        tenant_id="tenant-123",
        client_id="client-123",
        default_owner_unit_id="IT",
        validate_signature=True,
        jwks=jwks,
    )
    assert actor.user_id == "user-kadmin"
    assert actor.role == "KNOWLEDGE_ADMIN"


def test_entra_auth_tampered_signature_rejected() -> None:
    _priv_key1, jwk1 = _generate_rsa_key_and_jwk("kid-1")
    priv_key2, _ = _generate_rsa_key_and_jwk("kid-2")
    jwks = {"keys": [jwk1]}

    payload = {
        "sub": "user-attacker",
        "aud": "client-123",
        "iss": "https://login.microsoftonline.com/tenant-123/v2.0",
        "exp": int(time.time()) + 3600,
    }
    # Token signed with key2, but header claims kid-1
    token = jwt.encode(payload, priv_key2, algorithm="RS256", headers={"kid": "kid-1"})

    with pytest.raises(EntraAuthError, match="Signature verification failed"):
        resolve_actor_from_entra(
            token,
            tenant_id="tenant-123",
            client_id="client-123",
            default_owner_unit_id="IT",
            validate_signature=True,
            jwks=jwks,
        )


def test_entra_auth_expired_token_rejected() -> None:
    priv_key, jwk = _generate_rsa_key_and_jwk("kid-1")
    jwks = {"keys": [jwk]}

    payload = {
        "sub": "user-expired",
        "aud": "client-123",
        "iss": "https://login.microsoftonline.com/tenant-123/v2.0",
        "exp": int(time.time()) - 60,
    }
    token = jwt.encode(payload, priv_key, algorithm="RS256", headers={"kid": "kid-1"})

    with pytest.raises(EntraAuthError, match="Signature has expired"):
        resolve_actor_from_entra(
            token,
            tenant_id="tenant-123",
            client_id="client-123",
            default_owner_unit_id="IT",
            validate_signature=True,
            jwks=jwks,
        )


def test_entra_auth_invalid_audience_rejected() -> None:
    priv_key, jwk = _generate_rsa_key_and_jwk("kid-1")
    jwks = {"keys": [jwk]}

    payload = {
        "sub": "user-wrong-aud",
        "aud": "wrong-client-id",
        "iss": "https://login.microsoftonline.com/tenant-123/v2.0",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, priv_key, algorithm="RS256", headers={"kid": "kid-1"})

    with pytest.raises(EntraAuthError, match="Audience"):
        resolve_actor_from_entra(
            token,
            tenant_id="tenant-123",
            client_id="client-123",
            default_owner_unit_id="IT",
            validate_signature=True,
            jwks=jwks,
        )


def test_entra_auth_invalid_issuer_rejected() -> None:
    priv_key, jwk = _generate_rsa_key_and_jwk("kid-1")
    jwks = {"keys": [jwk]}

    payload = {
        "sub": "user-bad-iss",
        "aud": "client-123",
        "iss": "https://evil.attacker.com/tenant-123/v2.0",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, priv_key, algorithm="RS256", headers={"kid": "kid-1"})

    with pytest.raises(EntraAuthError, match="Invalid issuer"):
        resolve_actor_from_entra(
            token,
            tenant_id="tenant-123",
            client_id="client-123",
            default_owner_unit_id="IT",
            validate_signature=True,
            jwks=jwks,
        )


def test_entra_auth_unknown_kid_rejected() -> None:
    priv_key, jwk = _generate_rsa_key_and_jwk("kid-registered")
    jwks = {"keys": [jwk]}

    payload = {
        "sub": "user-unknown-kid",
        "aud": "client-123",
        "iss": "https://login.microsoftonline.com/tenant-123/v2.0",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, priv_key, algorithm="RS256", headers={"kid": "kid-unregistered"})

    with pytest.raises(EntraAuthError, match="not found in JWKS"):
        resolve_actor_from_entra(
            token,
            tenant_id="tenant-123",
            client_id="client-123",
            default_owner_unit_id="IT",
            validate_signature=True,
            jwks=jwks,
        )


def test_entra_auth_production_cannot_disable_signature_validation() -> None:
    with (
        patch.dict("os.environ", {"AGENT_DEPLOYMENT_ENV": "production"}),
        pytest.raises(EntraAuthError, match="cannot be disabled in production"),
    ):
        resolve_actor_from_entra(
            "dummy.token.here",
            tenant_id="tenant-123",
            client_id="client-123",
            default_owner_unit_id="IT",
            validate_signature=False,
        )


def test_backoffice_resolve_actor_converts_entra_error_to_backoffice_auth_error() -> None:
    priv_key, _jwk = _generate_rsa_key_and_jwk("kid-1")

    payload = {
        "sub": "user-exp",
        "aud": "client-123",
        "iss": "https://login.microsoftonline.com/tenant-123/v2.0",
        "exp": int(time.time()) - 100,
    }
    expired_token = jwt.encode(payload, priv_key, algorithm="RS256", headers={"kid": "kid-1"})

    with patch("ai_ops_backoffice.auth.resolve_actor_from_entra") as mock_resolve:
        mock_resolve.side_effect = EntraAuthError("Token validation failed: Signature has expired.")
        with pytest.raises(BackofficeAuthError, match="Signature has expired"):
            resolve_actor(
                auth_mode="ENTRA",
                authorization=f"Bearer {expired_token}",
                header_user_id=None,
                header_user_name=None,
                header_role=None,
                header_owner_units=None,
                default_owner_unit_id="IT",
                entra_tenant_id="tenant-123",
                entra_client_id="client-123",
            )
