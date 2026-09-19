"""Viewer tokens, HMAC signing, and citation viewer identity helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from time import time
from typing import Any

from teams_agent.settings import AgentSettings

_SOURCE_SIGN_PREFIX = "rag-source-v3\n"
_ALLOWED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}
_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_AGENTS_PLAYGROUND_TENANT_ID = "00000000-0000-0000-0000-0000000000001"

__all__ = [
    "ALLOWED_SUFFIXES",
    "SAFE_RELEASE_ID",
    "CitationViewerContext",
    "active_release_id",
    "citation_delivery_path",
    "citation_source_groups",
    "citation_source_tenant_id",
    "create_viewer_token",
    "normalize_source_path",
    "original_delivery_path",
    "sign_source_access",
    "sign_source_path",
    "verify_viewer_token",
]

# Stable aliases for sibling modules.
ALLOWED_SUFFIXES = _ALLOWED_SUFFIXES
SAFE_RELEASE_ID = _SAFE_RELEASE_ID


def create_viewer_token(
    subject: str,
    settings: AgentSettings,
    *,
    tenant_id: str | None = None,
    expires_in: int = 3600,
    now: float | None = None,
) -> str:
    """Mint a cryptographically signed HMAC viewer token."""

    key = settings.asset_signing_key or ""
    if not key:
        raise ValueError("asset_signing_key is required to create a viewer token.")
    current_time = int(time()) if now is None else int(now)
    payload_dict = {
        "sub": str(subject).strip(),
        "tid": str(tenant_id).strip() if tenant_id else None,
        "exp": current_time + max(1, int(expires_in)),
        "iat": current_time,
    }
    payload_bytes = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    import base64

    encoded_payload = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    signature = hmac.new(
        key.encode("utf-8"),
        f"v1.{encoded_payload}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"v1.{encoded_payload}.{signature}"


def verify_viewer_token(
    token: str,
    settings: AgentSettings,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Verify an HMAC viewer token against asset_signing_key."""

    key = settings.asset_signing_key or ""
    if not key or not token or not isinstance(token, str):
        return None
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != "v1":
        return None
    _, encoded_payload, signature = parts
    expected = hmac.new(
        key.encode("utf-8"),
        f"v1.{encoded_payload}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        import base64

        padded = encoded_payload + "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        exp = int(payload.get("exp", 0))
        current = int(time()) if now is None else int(now)
        if exp < current:
            return None
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


@dataclass(frozen=True)
class CitationViewerContext:
    """Viewer identity used when minting and opening citation links."""

    subject: str
    groups: tuple[str, ...] = ()
    tenant_id: str | None = None
    revoked: bool = False


def citation_source_tenant_id(channel: str, tenant_id: str | None) -> str | None:
    """Map the synthetic Agents Playground tenant to the shared lab corpus."""
    if channel.casefold() == "playground" and tenant_id == _AGENTS_PLAYGROUND_TENANT_ID:
        return "default"
    return tenant_id


def citation_source_groups(
    channel: str,
    tenant_id: str | None,
    groups: tuple[str, ...],
) -> tuple[str, ...]:
    """Supply the public corpus group for synthetic Playground identities."""
    if (
        channel.casefold() == "playground"
        and tenant_id == _AGENTS_PLAYGROUND_TENANT_ID
        and not groups
    ):
        return ("grp_public",)
    return groups


def sign_source_access(
    path: str,
    expires: int,
    key: str,
    *,
    subject: str,
    source_ref_id: str | None = None,
    tenant_id: str | None = None,
    groups: tuple[str, ...] | list[str] = (),
) -> str:
    """HMAC binding for source delivery.

    ``groups`` is accepted for call-site compatibility but intentionally ignored:
    ACL membership must be re-resolved on every open.
    """

    _ = groups
    payload = (
        f"{_SOURCE_SIGN_PREFIX}{path}\n{expires}\n{subject}\n"
        f"{source_ref_id or ''}\n{tenant_id or ''}"
    ).encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def sign_source_path(path: str, expires: int, key: str) -> str:
    """Legacy path-only signature retained for asset-style helpers/tests."""

    payload = f"rag-source\n{path}\n{expires}".encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def normalize_source_path(path: str) -> PurePosixPath | None:
    candidate = str(path or "").replace("\\", "/").strip()
    if not candidate or "://" in candidate:
        return None
    pure_path = PurePosixPath(candidate)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        return None
    if not pure_path.parts:
        return None
    return pure_path


def active_release_id(settings: AgentSettings) -> str | None:
    source_dir = (settings.source_dir or Path()).resolve()
    pointer = source_dir / "releases" / "active_release.json"
    if not pointer.is_file():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = payload.get("releaseId") or payload.get("release_id")
    if not isinstance(value, str) or not _SAFE_RELEASE_ID.fullmatch(value):
        return None
    return value


def citation_delivery_path(
    source_path: str,
    settings: AgentSettings,
    *,
    release_id: str | None = None,
) -> str | None:
    """Map a citation sourcePath to a filesystem-relative delivery path."""

    pure_path = normalize_source_path(source_path)
    if pure_path is None:
        return None
    path = pure_path.as_posix()
    if path.startswith("releases/"):
        return path

    source_root = (settings.source_dir or Path()).resolve()
    direct = source_root / path
    preferred_release = (release_id or "").strip() or active_release_id(settings)
    if preferred_release and _SAFE_RELEASE_ID.fullmatch(preferred_release):
        release_relative = f"releases/{preferred_release}/{path}"
        release_file = source_root / release_relative
        if release_file.is_file():
            return release_relative
        if pure_path.name.startswith("doc--"):
            return release_relative

    if direct.is_file():
        return path
    return path


def original_delivery_path(source_ref_id: str) -> str | None:
    source_ref = str(source_ref_id or "").strip()
    if not source_ref or "/" in source_ref or ".." in source_ref:
        return None
    return f"originals/{source_ref}"
