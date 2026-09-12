"""Signed citation links for knowledge source markdown files.

Knowledge citations often arrive without a formal document URL. When the Agent
Service includes ``sourcePath``, the adapter mints a short-lived signed URL under
``/rag-sources/`` so Playground and Teams can render clickable markdown links.

Authorization is not signature-only (Spec F02 / PR-2):

- Signature binds path, expiry, subject, and optional sourceRefId.
- ACL groups are never taken from the URL; membership is re-resolved on each
  open from the live viewer session cache (refreshed on bot turns).
- Document ACL is evaluated with the same rules as
  ``authorize_document_access`` (tenant, revocation, ACL groups).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import mimetypes
import re
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from time import time
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

from .contracts import AgentResponse, Citation
from .settings import AgentSettings
from .viewer_sessions import (
    InMemoryViewerMembershipStore,
    ViewerMembership,
    ViewerMembershipResolver,
    get_viewer_membership_store,
)

_SOURCE_SIGN_PREFIX = "rag-source-v3\n"
_ALLOWED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}
_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
logger = logging.getLogger(__name__)


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

    pure_path = _normalize_source_path(source_path)
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


def build_source_url(
    path: str,
    settings: AgentSettings,
    now: int | None = None,
    *,
    release_id: str | None = None,
    viewer: CitationViewerContext | None = None,
    source_ref_id: str | None = None,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None = None,
) -> str | None:
    if not settings.sources_ready:
        return None
    if viewer is None or not str(viewer.subject or "").strip():
        # Spec requires a bound viewer identity; refuse transferable anonymous links.
        return None
    delivery = citation_delivery_path(path, settings, release_id=release_id)
    if delivery is None:
        return None
    subject = str(viewer.subject).strip()
    issued_at = int(time()) if now is None else now
    expires = issued_at + settings.asset_url_ttl_seconds
    store = membership_store or get_viewer_membership_store(settings)
    store.remember(
        subject,
        groups=viewer.groups,
        tenant_id=viewer.tenant_id,
        revoked=viewer.revoked,
        ttl_seconds=float(settings.asset_url_ttl_seconds),
        now=float(issued_at),
    )
    signature = sign_source_access(
        delivery,
        expires,
        settings.asset_signing_key or "",
        subject=subject,
        source_ref_id=source_ref_id,
        tenant_id=viewer.tenant_id,
    )
    encoded_path = quote(delivery, safe="/")
    query = (
        f"expires={expires}&signature={signature}"
        f"&subject={quote(subject, safe='')}"
    )
    if source_ref_id:
        query += f"&sourceRefId={quote(source_ref_id, safe='')}"
    if viewer.tenant_id:
        query += f"&tenantId={quote(str(viewer.tenant_id), safe='')}"
    return f"{settings.public_base_url}/rag-sources/{encoded_path}?{query}"


def resolve_source_file(
    path: str,
    expires: str | None,
    signature: str | None,
    settings: AgentSettings,
    now: int | None = None,
    *,
    subject: str | None = None,
    groups: str | None = None,
    source_ref_id: str | None = None,
    tenant_id: str | None = None,
    revoked: bool = False,
    authenticated_subject: str | None = None,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None = None,
) -> Path:
    if not settings.sources_ready:
        raise PermissionError("RAG source delivery is not configured.")
    try:
        expiry = int(expires or "")
    except ValueError as error:
        raise PermissionError("Invalid source expiry.") from error
    current_time = int(time()) if now is None else now
    if expiry < current_time or expiry > current_time + settings.asset_url_ttl_seconds:
        raise PermissionError("Source URL has expired or has an invalid lifetime.")

    pure_path = _normalize_source_path(path)
    if pure_path is None:
        raise PermissionError("Invalid source path.")
    delivery = pure_path.as_posix()
    claimed_subject = str(subject or "").strip()
    if not claimed_subject:
        raise PermissionError("Viewer identity is required to open a source citation.")

    # Login identity check: strictly enforce authenticated subject in production
    auth_subject = str(authenticated_subject or "").strip()
    if not settings.allow_unauthenticated_requests:
        if not auth_subject:
            raise PermissionError("Viewer authentication is required to open a source citation.")
        if auth_subject != claimed_subject:
            raise PermissionError("Viewer identity does not match the signed citation subject.")
        viewer_subject = auth_subject
    else:
        if auth_subject and auth_subject != claimed_subject:
            raise PermissionError("Viewer identity does not match the signed citation subject.")
        viewer_subject = auth_subject or claimed_subject

    expected = sign_source_access(
        delivery,
        expiry,
        settings.asset_signing_key or "",
        subject=claimed_subject,
        source_ref_id=source_ref_id,
        tenant_id=tenant_id,
    )
    if not signature or not hmac.compare_digest(signature, expected):
        raise PermissionError("Invalid source signature or viewer binding.")

    source_dir = (settings.source_dir or Path()).resolve()
    resolved = (source_dir / pure_path).resolve()
    try:
        resolved.relative_to(source_dir)
    except ValueError as error:
        raise PermissionError("Invalid source path.") from error
    if not resolved.is_file():
        if not delivery.startswith("releases/"):
            fallback = citation_delivery_path(delivery, settings)
            if fallback and fallback != delivery:
                candidate = (source_dir / fallback).resolve()
                try:
                    candidate.relative_to(source_dir)
                except ValueError as error:
                    raise PermissionError("Invalid source path.") from error
                if candidate.is_file():
                    resolved = candidate
                    delivery = fallback
                else:
                    raise FileNotFoundError(path)
            else:
                raise FileNotFoundError(path)
        else:
            raise FileNotFoundError(path)
    if resolved.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise PermissionError("Unsupported source file type.")

    # Re-authorize against live membership + document ACL on every open.
    # URL ``groups`` claims are ignored (Spec: re-authorize, do not trust link).
    _ = groups
    authorize_source_open(
        settings,
        delivery_path=delivery,
        subject=viewer_subject,
        tenant_id=tenant_id,
        revoked=revoked,
        source_ref_id=source_ref_id,
        membership_store=membership_store,
        now=float(current_time),
    )
    return resolved


def authorize_source_open(
    settings: AgentSettings,
    *,
    delivery_path: str,
    subject: str,
    tenant_id: str | None = None,
    revoked: bool = False,
    source_ref_id: str | None = None,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None = None,
    now: float | None = None,
) -> None:
    """Re-check document ACL with live viewer membership (shared-auth rules)."""

    if revoked or not subject:
        raise PermissionError("Source reference not found or access denied.")

    store = membership_store or get_viewer_membership_store(settings)
    membership = store.resolve(subject, now=now)
    if membership is None:
        raise PermissionError("Source reference not found or access denied.")
    if membership.revoked:
        raise PermissionError("Source reference not found or access denied.")

    # Validate that if the URL claimed a tenant, it matches the viewer's live membership tenant
    if (
        tenant_id
        and membership.tenant_id
        and str(tenant_id).strip() != str(membership.tenant_id).strip()
    ):
        raise PermissionError("Viewer tenant does not match citation tenant.")

    effective_tenant = membership.tenant_id or tenant_id

    document = load_source_acl_document(
        settings,
        delivery_path,
        source_ref_id=source_ref_id,
    )
    if document is None:
        # Bundled corpus without ACL metadata is treated as tenant-open for the
        # bound subject that still has a live membership session.
        return

    actor = SimpleNamespace(
        user_id=subject,
        tenant_id=effective_tenant,
        groups=list(membership.groups),
        revoked=membership.revoked,
        active=not membership.revoked,
        role="",
        capabilities=(),
        owner_unit_ids=(),
    )
    decision = _authorize_document_access(actor, document)
    if not decision["allowed"]:
        raise PermissionError("Source reference not found or access denied.")


def _authorize_document_access(actor: Any, document: dict[str, Any]) -> dict[str, Any]:
    """Mirror agent_service.document_authorization rules for Teams delivery."""

    if bool(getattr(actor, "revoked", False)) or getattr(actor, "active", True) is False:
        return {"allowed": False, "reason": "REVOKED"}

    actor_tenant = getattr(actor, "tenant_id", None)
    doc_tenant = document.get("tenant_id")
    if doc_tenant and (not actor_tenant or str(actor_tenant) != str(doc_tenant)):
        return {"allowed": False, "reason": "TENANT_MISMATCH"}


    if bool(document.get("is_deleted")):
        return {"allowed": False, "reason": "DELETED"}
    if bool(document.get("is_archived")):
        return {"allowed": False, "reason": "ARCHIVED"}

    acl_groups = [
        str(item).strip()
        for item in (document.get("acl_groups") or document.get("allowed_groups") or [])
        if str(item).strip()
    ]
    if acl_groups:
        actor_groups = {str(item).strip() for item in (getattr(actor, "groups", []) or [])}
        if not actor_groups.intersection(acl_groups):
            return {"allowed": False, "reason": "ACL_DENIED"}
    return {"allowed": True, "reason": "ACCESS_GRANTED"}


def load_source_acl_document(
    settings: AgentSettings,
    delivery_path: str,
    *,
    source_ref_id: str | None = None,
) -> dict[str, object] | None:
    source_root = (settings.source_dir or Path()).resolve()
    release_id: str | None = None
    source_path = delivery_path
    parts = PurePosixPath(delivery_path).parts
    if len(parts) >= 3 and parts[0] == "releases":
        release_id = parts[1]
        source_path = "/".join(parts[2:])
    elif not release_id:
        release_id = active_release_id(settings)

    # Prefer SourceRecord index when sourceRefId is present (Spec PR-2).
    if source_ref_id and release_id and _SAFE_RELEASE_ID.fullmatch(release_id):
        record = _load_source_record(source_root, release_id, source_ref_id)
        if record is not None:
            return record

    if not release_id or not _SAFE_RELEASE_ID.fullmatch(release_id):
        return None
    index_path = source_root / "releases" / release_id / "index" / "chunks.json"
    if not index_path.is_file():
        return None
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    chunks = payload.get("chunks") if isinstance(payload, dict) else None
    if not isinstance(chunks, list):
        return None
    for item in chunks:
        if not isinstance(item, dict):
            continue
        item_path = str(item.get("source_path") or item.get("sourcePath") or "")
        if item_path.replace("\\", "/") != source_path:
            continue
        return {
            "source_path": item_path,
            "tenant_id": item.get("tenant_id") or item.get("tenantId"),
            "acl_groups": item.get("allowed_groups")
            or item.get("allowedGroups")
            or item.get("acl_groups")
            or [],
            "owner_unit_id": item.get("owner_unit_id") or item.get("ownerUnitId"),
            "is_deleted": bool(item.get("is_deleted") or item.get("isDeleted")),
            "is_archived": bool(item.get("is_archived") or item.get("isArchived")),
            "title": item.get("title"),
        }
    return None


def _load_source_record(
    source_root: Path,
    release_id: str,
    source_ref_id: str,
) -> dict[str, object] | None:
    candidates = [
        source_root / "releases" / release_id / "index" / "sources.json",
        source_root / "source_records" / f"{source_ref_id}.json",
        source_root / "sources" / "records" / f"{source_ref_id}.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        records: list[Any]
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            records = payload["records"]
        elif isinstance(payload, dict) and isinstance(payload.get("sources"), list):
            records = payload["sources"]
        elif isinstance(payload, dict):
            records = [payload]
        elif isinstance(payload, list):
            records = payload
        else:
            continue
        for item in records:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("source_ref_id") or item.get("sourceRefId") or "")
            if ref != source_ref_id:
                continue
            return {
                "source_ref_id": ref,
                "tenant_id": item.get("tenant_id") or item.get("tenantId"),
                "acl_groups": item.get("acl_groups")
                or item.get("aclGroups")
                or item.get("allowed_groups")
                or [],
                "owner_unit_id": item.get("owner_unit_id") or item.get("ownerUnitId"),
                "is_deleted": bool(item.get("is_deleted") or item.get("isDeleted")),
                "is_archived": bool(item.get("is_archived") or item.get("isArchived")),
                "title": item.get("title"),
                "source_path": item.get("source_path") or item.get("sourcePath"),
            }
    return None


def source_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    return "text/plain; charset=utf-8"


def enrich_citation_urls(
    response: AgentResponse,
    settings: AgentSettings,
    *,
    now: int | None = None,
    viewer: CitationViewerContext | None = None,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None = None,
) -> AgentResponse:
    """Fill missing citation URLs from ``sourcePath`` when delivery is ready."""

    if not response.citations or not settings.sources_ready:
        return response
    enriched: list[Citation] = []
    changed = False
    for citation in response.citations:
        if citation.url or not citation.sourcePath:
            enriched.append(citation)
            continue
        url = build_source_url(
            citation.sourcePath,
            settings,
            now=now,
            release_id=citation.releaseId,
            viewer=viewer,
            source_ref_id=citation.sourceRefId,
            membership_store=membership_store,
        )
        if not url:
            enriched.append(citation)
            continue
        enriched.append(replace(citation, url=url))
        changed = True
    if not changed:
        return response
    return replace(response, citations=enriched)


def register_viewer_membership(
    viewer: CitationViewerContext,
    settings: AgentSettings,
    *,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None = None,
    now: float | None = None,
) -> ViewerMembership | None:
    """Refresh live membership from an authenticated bot/Playground turn."""

    subject = str(viewer.subject or "").strip()
    if not subject:
        return None
    store = membership_store or get_viewer_membership_store(settings)
    return store.remember(
        subject,
        groups=viewer.groups,
        tenant_id=viewer.tenant_id,
        revoked=viewer.revoked,
        ttl_seconds=float(settings.asset_url_ttl_seconds),
        now=now,
    )



def _normalize_source_path(path: str) -> PurePosixPath | None:
    candidate = str(path or "").replace("\\", "/").strip()
    if not candidate or "://" in candidate:
        return None
    pure_path = PurePosixPath(candidate)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        return None
    if not pure_path.parts:
        return None
    return pure_path
