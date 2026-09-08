"""Knowledge index-status derivation is independent of lifecycle labels."""

from ai_ops_backoffice.services.query_knowledge import (
    _derive_index_status,
    _normalize_format_type,
)


def test_normalize_format_type_collapses_markdown_variants() -> None:
    assert _normalize_format_type("MARKDOWN_UPLOAD") == "MARKDOWN"
    assert _normalize_format_type("MARKDOWN_PASTE") == "MARKDOWN"
    assert _normalize_format_type("PDF") == "PDF"
    assert _normalize_format_type(None) == "UNKNOWN"


def test_derive_index_status_uses_active_release_membership() -> None:
    assert (
        _derive_index_status(
            lifecycle_status="PUBLISHED",
            has_published_version=True,
            parse_status="READY",
            indexed_document_ids={"doc-1"},
            document_id="doc-1",
        )
        == "INDEXED"
    )
    assert (
        _derive_index_status(
            lifecycle_status="PUBLISHED",
            has_published_version=True,
            parse_status="READY",
            indexed_document_ids={"doc-other"},
            document_id="doc-1",
        )
        == "PENDING_INDEX"
    )
    assert (
        _derive_index_status(
            lifecycle_status="DRAFT",
            has_published_version=False,
            parse_status="NOT_PARSED",
            indexed_document_ids=set(),
            document_id="doc-1",
        )
        == "NOT_INDEXED"
    )
    assert (
        _derive_index_status(
            lifecycle_status="PUBLISHED",
            has_published_version=True,
            parse_status="NOT_PARSED",
            indexed_document_ids={"doc-1"},
            document_id="doc-1",
        )
        == "NOT_PARSED"
    )
