"""Citation URL enrichment and re-exports from citation_asset_gateway.

URL minting and ACL live in ``citation_asset_gateway``. Enrichment stays here
because it depends on ``teams_agent.contracts`` (Citation / AgentResponse).
"""

from __future__ import annotations

from dataclasses import replace

from citation_asset_gateway.source_links import (
    CitationViewerContext,
    active_release_id,
    authorize_original_open,
    authorize_source_open,
    build_citation_preview_url,
    build_original_url,
    build_source_url,
    citation_delivery_path,
    citation_source_groups,
    citation_source_tenant_id,
    create_viewer_token,
    is_adapter_original_delivery_url,
    is_adapter_source_delivery_url,
    load_source_acl_document,
    register_viewer_membership,
    resolve_source_file,
    sign_source_access,
    sign_source_path,
    source_media_type,
    verify_viewer_token,
)
from citation_asset_gateway.viewer_sessions import (
    InMemoryViewerMembershipStore,
    ViewerMembershipResolver,
)

from .contracts import AgentResponse, Citation
from .settings import AgentSettings

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
            citation.url and is_adapter_source_delivery_url(citation.url, settings)
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
            and is_adapter_original_delivery_url(updated.originalUrl, settings)
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
