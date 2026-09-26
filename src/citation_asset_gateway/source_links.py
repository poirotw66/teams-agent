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

Signing and open-path authorization live in sibling modules; this module owns
URL minting, citation enrichment, and stable public re-exports.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from time import time
from urllib.parse import quote

from .settings_contract import CitationGatewaySettings
from .source_link_access import (
    authorize_original_open,
    authorize_source_open,
    load_source_acl_document,
    resolve_source_file,
)
from .source_link_signing import (
    CitationViewerContext,
    active_release_id,
    citation_delivery_path,
    citation_source_file_exists,
    citation_source_groups,
    citation_source_tenant_id,
    create_viewer_token,
    original_delivery_path,
    sign_source_access,
    sign_source_path,
    verify_viewer_token,
)
from .viewer_sessions import (
    InMemoryViewerMembershipStore,
    ViewerMembership,
    ViewerMembershipResolver,
    get_viewer_membership_store,
)

__all__ = [
    "CitationViewerContext",
    "active_release_id",
    "authorize_original_open",
    "authorize_source_open",
    "build_citation_preview_url",
    "build_original_url",
    "build_source_url",
    "citation_delivery_path",
    "citation_source_file_exists",
    "citation_source_groups",
    "citation_source_tenant_id",
    "create_viewer_token",
    "is_adapter_citation_preview_url",
    "is_adapter_original_delivery_url",
    "is_adapter_source_delivery_url",
    "load_source_acl_document",
    "register_viewer_membership",
    "resolve_source_file",
    "sign_source_access",
    "sign_source_path",
    "source_media_type",
    "verify_viewer_token",
]


def build_source_url(
    path: str,
    settings: CitationGatewaySettings,
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


def build_original_url(
    source_ref_id: str,
    settings: CitationGatewaySettings,
    now: int | None = None,
    *,
    viewer: CitationViewerContext | None = None,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None = None,
) -> str | None:
    """Mint a short-lived signed URL for Backoffice original-file delivery."""

    if not settings.source_api_ready:
        return None
    if viewer is None or not str(viewer.subject or "").strip():
        return None
    delivery = original_delivery_path(source_ref_id)
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
    query = (
        f"expires={expires}&signature={signature}"
        f"&subject={quote(subject, safe='')}"
    )
    if viewer.tenant_id:
        query += f"&tenantId={quote(str(viewer.tenant_id), safe='')}"
    encoded_ref = quote(str(source_ref_id).strip(), safe="")
    return f"{settings.public_base_url}/rag-originals/{encoded_ref}?{query}"


def build_citation_preview_url(
    source_ref_id: str,
    settings: CitationGatewaySettings,
    now: int | None = None,
    *,
    viewer: CitationViewerContext | None = None,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None = None,
) -> str | None:
    """Mint a signed URL for a governed citation preview."""

    original_url = build_original_url(
        source_ref_id,
        settings,
        now,
        viewer=viewer,
        membership_store=membership_store,
    )
    if original_url is None:
        return None
    preview_url = original_url.replace("/rag-originals/", "/rag-citations/", 1)
    return f"{preview_url}#citation-highlight"


def source_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    return "text/plain; charset=utf-8"


def is_adapter_source_delivery_url(url: str, settings: CitationGatewaySettings) -> bool:
    candidate = str(url or "").strip()
    if not candidate:
        return False
    if candidate.startswith("/rag-sources/"):
        return True
    base = str(settings.public_base_url or "").rstrip("/")
    return bool(base) and candidate.startswith(f"{base}/rag-sources/")


def is_adapter_original_delivery_url(url: str, settings: CitationGatewaySettings) -> bool:
    candidate = str(url or "").strip()
    if not candidate:
        return False
    if candidate.startswith("/rag-originals/"):
        return True
    base = str(settings.public_base_url or "").rstrip("/")
    return bool(base) and candidate.startswith(f"{base}/rag-originals/")


def is_adapter_citation_preview_url(url: str, settings: CitationGatewaySettings) -> bool:
    candidate = str(url or "").strip()
    if not candidate:
        return False
    if candidate.startswith("/rag-citations/"):
        return True
    base = str(settings.public_base_url or "").rstrip("/")
    return bool(base) and candidate.startswith(f"{base}/rag-citations/")


def register_viewer_membership(
    viewer: CitationViewerContext,
    settings: CitationGatewaySettings,
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
