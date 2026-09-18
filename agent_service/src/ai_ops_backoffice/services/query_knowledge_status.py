"""Knowledge document format and RAG index status helpers."""

from __future__ import annotations


def normalize_format_type(raw: str | None) -> str:
    value = str(raw or "UNKNOWN").upper()
    if value == "PDF":
        return "PDF"
    if value.startswith("MARKDOWN"):
        return "MARKDOWN"
    return value or "UNKNOWN"


def derive_index_status(
    *,
    lifecycle_status: str | None,
    has_published_version: bool,
    parse_status: str,
    indexed_document_ids: set[str] | None,
    document_id: str,
) -> str:
    """Return RAG index status distinct from document lifecycle."""
    lifecycle = str(lifecycle_status or "").upper()
    if not has_published_version:
        return "NOT_INDEXED"
    if parse_status != "READY":
        return "NOT_PARSED"
    if indexed_document_ids is None:
        # Portal release probe unavailable: published+parsed is treated as indexed
        # for local/single-node setups where publish activates the release.
        return "INDEXED" if lifecycle == "PUBLISHED" else "PENDING_INDEX"
    if document_id in indexed_document_ids:
        return "INDEXED"
    return "PENDING_INDEX"


# Backward-compatible private aliases used by existing tests/importers.
_normalize_format_type = normalize_format_type
_derive_index_status = derive_index_status
