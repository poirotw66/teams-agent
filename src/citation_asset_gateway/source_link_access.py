"""Authorization and filesystem resolution for signed source delivery."""

from __future__ import annotations

import hmac
import json
from pathlib import Path, PurePosixPath
from time import time
from types import SimpleNamespace
from typing import Any

from .settings_contract import CitationGatewaySettings
from .source_link_signing import (
    ALLOWED_SUFFIXES,
    SAFE_RELEASE_ID,
    CitationViewerContext,
    active_release_id,
    citation_delivery_path,
    normalize_source_path,
    original_delivery_path,
    sign_source_access,
)
from .viewer_sessions import (
    InMemoryViewerMembershipStore,
    ViewerMembershipResolver,
    get_viewer_membership_store,
)

__all__ = [
    "authorize_original_open",
    "authorize_source_open",
    "load_source_acl_document",
    "resolve_source_file",
]


def _parse_source_expiry(
    expires: str | None,
    *,
    settings: CitationGatewaySettings,
    now: int | None,
) -> tuple[int, int]:
    try:
        expiry = int(expires or "")
    except ValueError as error:
        raise PermissionError("Invalid source expiry.") from error
    current_time = int(time()) if now is None else now
    if expiry < current_time or expiry > current_time + settings.asset_url_ttl_seconds:
        raise PermissionError("Source URL has expired or has an invalid lifetime.")
    return expiry, current_time


def _bind_viewer_subject(
    *,
    subject: str | None,
    authenticated_subject: str | None,
    settings: CitationGatewaySettings,
) -> tuple[str, str]:
    claimed_subject = str(subject or "").strip()
    if not claimed_subject:
        raise PermissionError("Viewer identity is required to open a source citation.")

    auth_subject = str(authenticated_subject or "").strip()
    if not settings.allow_unauthenticated_requests:
        if not auth_subject:
            raise PermissionError("Viewer authentication is required to open a source citation.")
        if auth_subject != claimed_subject:
            raise PermissionError("Viewer identity does not match the signed citation subject.")
        return claimed_subject, auth_subject

    if auth_subject and auth_subject != claimed_subject:
        raise PermissionError("Viewer identity does not match the signed citation subject.")
    return claimed_subject, auth_subject or claimed_subject


def authorize_original_open(
    source_ref_id: str,
    expires: str | None,
    signature: str | None,
    settings: CitationGatewaySettings,
    now: int | None = None,
    *,
    subject: str | None = None,
    tenant_id: str | None = None,
    authenticated_subject: str | None = None,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None = None,
) -> CitationViewerContext:
    """Verify signature and resolve live viewer membership for original delivery."""

    if not settings.source_api_ready:
        raise PermissionError("Original source delivery is not configured.")
    expiry, current_time = _parse_source_expiry(expires, settings=settings, now=now)

    delivery = original_delivery_path(source_ref_id)
    if delivery is None:
        raise PermissionError("Invalid source reference.")
    claimed_subject, viewer_subject = _bind_viewer_subject(
        subject=subject,
        authenticated_subject=authenticated_subject,
        settings=settings,
    )

    expected = sign_source_access(
        delivery,
        expiry,
        settings.asset_signing_key or "",
        subject=claimed_subject,
        source_ref_id=source_ref_id,
        tenant_id=tenant_id,
    )
    if not signature or not hmac.compare_digest(str(signature), expected):
        raise PermissionError("Invalid source signature.")

    store = membership_store or get_viewer_membership_store(settings)
    membership = store.resolve(viewer_subject, now=float(current_time))
    if membership is None:
        raise PermissionError("Viewer membership is required to open a source citation.")
    if membership.revoked:
        raise PermissionError("Viewer access has been revoked.")
    claimed_tenant = str(tenant_id or "").strip() or None
    if claimed_tenant and membership.tenant_id and claimed_tenant != membership.tenant_id:
        raise PermissionError("Viewer tenant does not match the signed citation tenant.")

    return CitationViewerContext(
        subject=viewer_subject,
        groups=membership.groups,
        tenant_id=membership.tenant_id or claimed_tenant,
        revoked=False,
    )


def _locate_resolved_source_file(
    *,
    source_dir: Path,
    pure_path: PurePosixPath,
    delivery: str,
    settings: CitationGatewaySettings,
    original_path: str,
) -> tuple[Path, str]:
    resolved = (source_dir / pure_path).resolve()
    try:
        resolved.relative_to(source_dir)
    except ValueError as error:
        raise PermissionError("Invalid source path.") from error
    if resolved.is_file():
        return resolved, delivery
    if delivery.startswith("releases/"):
        raise FileNotFoundError(original_path)
    fallback = citation_delivery_path(delivery, settings)
    if not fallback or fallback == delivery:
        raise FileNotFoundError(original_path)
    candidate = (source_dir / fallback).resolve()
    try:
        candidate.relative_to(source_dir)
    except ValueError as error:
        raise PermissionError("Invalid source path.") from error
    if not candidate.is_file():
        raise FileNotFoundError(original_path)
    return candidate, fallback


def resolve_source_file(
    path: str,
    expires: str | None,
    signature: str | None,
    settings: CitationGatewaySettings,
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
    expiry, current_time = _parse_source_expiry(expires, settings=settings, now=now)

    pure_path = normalize_source_path(path)
    if pure_path is None:
        raise PermissionError("Invalid source path.")
    delivery = pure_path.as_posix()
    claimed_subject, viewer_subject = _bind_viewer_subject(
        subject=subject,
        authenticated_subject=authenticated_subject,
        settings=settings,
    )

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
    resolved, delivery = _locate_resolved_source_file(
        source_dir=source_dir,
        pure_path=pure_path,
        delivery=delivery,
        settings=settings,
        original_path=path,
    )
    if resolved.suffix.lower() not in ALLOWED_SUFFIXES:
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
    settings: CitationGatewaySettings,
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
    settings: CitationGatewaySettings,
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

    if source_ref_id and release_id and SAFE_RELEASE_ID.fullmatch(release_id):
        record = _load_source_record(source_root, release_id, source_ref_id)
        if record is not None:
            return record

    if not release_id or not SAFE_RELEASE_ID.fullmatch(release_id):
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
