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
from dataclasses import replace
from pathlib import Path
from time import time
from urllib.parse import quote

from teams_agent.contracts import AgentResponse, Citation
from teams_agent.settings import AgentSettings
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
    "citation_source_groups",
    "citation_source_tenant_id",
    "create_viewer_token",
    "enrich_citation_urls",
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


def build_original_url(
    source_ref_id: str,
    settings: AgentSettings,
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
    settings: AgentSettings,
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


def _is_adapter_source_delivery_url(url: str, settings: AgentSettings) -> bool:
    candidate = str(url or "").strip()
    if not candidate:
        return False
    if candidate.startswith("/rag-sources/"):
        return True
    base = str(settings.public_base_url or "").rstrip("/")
    return bool(base) and candidate.startswith(f"{base}/rag-sources/")


def _is_adapter_original_delivery_url(url: str, settings: AgentSettings) -> bool:
    candidate = str(url or "").strip()
    if not candidate:
        return False
    if candidate.startswith("/rag-originals/"):
        return True
    base = str(settings.public_base_url or "").rstrip("/")
    return bool(base) and candidate.startswith(f"{base}/rag-originals/")


def _enrich_one_citation(
    citation: Citation,
    *,
    settings: AgentSettings,
    now: int | None,
    viewer: CitationViewerContext | None,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None,
    can_mint_markdown: bool,
    can_mint_original: bool,
) -> tuple[Citation, bool]:
    updated = citation
    changed = False
    if (
        can_mint_markdown
        and citation.sourcePath
        and not (
            citation.url and _is_adapter_source_delivery_url(citation.url, settings)
        )
    ):
        url = build_source_url(
            citation.sourcePath,
            settings,
            now=now,
            release_id=citation.releaseId,
            viewer=viewer,
            source_ref_id=citation.sourceRefId,
            membership_store=membership_store,
        )
        if url:
            updated = replace(updated, url=url)
            changed = True

    if can_mint_original and citation.sourceRefId and not updated.url:
        preview_url = build_citation_preview_url(
            citation.sourceRefId,
            settings,
            now,
            viewer=viewer,
            membership_store=membership_store,
        )
        if preview_url:
            updated = replace(updated, url=preview_url)
            changed = True

    if (
        can_mint_original
        and citation.sourceRefId
        and not (
            updated.originalUrl
            and _is_adapter_original_delivery_url(updated.originalUrl, settings)
        )
    ):
        original_url = build_original_url(
            citation.sourceRefId,
            settings,
            now=now,
            viewer=viewer,
            membership_store=membership_store,
        )
        if original_url:
            updated = replace(updated, originalUrl=original_url)
            changed = True
    return updated, changed


def enrich_citation_urls(
    response: AgentResponse,
    settings: AgentSettings,
    *,
    now: int | None = None,
    viewer: CitationViewerContext | None = None,
    membership_store: InMemoryViewerMembershipStore | ViewerMembershipResolver | None = None,
) -> AgentResponse:
    """Fill citation delivery URLs for markdown viewers and original files.

    Prefer signed ``/rag-sources/`` delivery when a local ``sourcePath`` exists.
    Prefer signed ``/rag-originals/`` when Source API is configured and a
    ``sourceRefId`` is present. Agent-minted formal URLs that are not already
    adapter delivery links are replaced so Playground/Teams open the shared
    viewer instead of a dead path.
    """

    if not response.citations:
        return response
    can_mint_markdown = settings.sources_ready
    can_mint_original = settings.source_api_ready
    if not can_mint_markdown and not can_mint_original:
        return response

    enriched: list[Citation] = []
    changed = False
    for citation in response.citations:
        updated, citation_changed = _enrich_one_citation(
            citation,
            settings=settings,
            now=now,
            viewer=viewer,
            membership_store=membership_store,
            can_mint_markdown=can_mint_markdown,
            can_mint_original=can_mint_original,
        )
        changed = changed or citation_changed
        enriched.append(updated)
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
