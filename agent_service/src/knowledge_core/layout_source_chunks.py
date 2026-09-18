"""Layout-aware source chunk loading for Portal and Agent ingestion.

Uses Markdown layout parsing + profile chunking without importing Agent
runtime modules. Agent ``documents`` keeps a compatibility facade.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_core.chunking_profile import ChunkingProfile
from knowledge_core.document_chunks import DocumentChunk, DocumentMetadata, extract_images
from knowledge_core.document_chunks import chunk_markdown as _chunk_markdown
from knowledge_core.document_chunks import (
    load_source_chunks as _load_source_chunks,
)
from knowledge_core.document_layout import MarkdownLayoutParser
from knowledge_core.layout_chunking import chunk_parsed_document

__all__ = [
    "chunk_layout_markdown",
    "chunk_markdown_with_layout",
    "load_source_chunks_with_layout",
]


def _metadata_string_list(metadata: dict[str, Any], field_name: str) -> list[str]:
    value = metadata.get(field_name) or []
    if not isinstance(value, list):
        raise TypeError(f"Metadata field '{field_name}' must be a list of strings.")
    return [str(item).strip() for item in value if str(item).strip()]


def chunk_layout_markdown(
    *,
    source_path: Path,
    relative_path: str,
    canonical_markdown: str,
    title: str,
    metadata: dict[str, Any],
    allowed_groups: list[str],
    doc_metadata: DocumentMetadata | None,
) -> list[DocumentChunk]:
    profile_value = str(metadata.get("chunkingProfile") or "AUTO").upper()
    try:
        profile = ChunkingProfile(profile_value)
    except ValueError:
        profile = ChunkingProfile.AUTO
    document_id = str(metadata.get("documentId") or source_path.stem)
    parsed = MarkdownLayoutParser().parse(canonical_markdown, title=title)
    drafts, _quality = chunk_parsed_document(
        parsed,
        document_id=document_id,
        profile=profile,
    )
    return [
        DocumentChunk(
            chunk_id=draft.chunk_id,
            title=title,
            source_path=relative_path,
            content=draft.content,
            classification=str(metadata.get("classification", "internal")),
            allowed_groups=allowed_groups,
            images=extract_images(draft.content, source_path),
            metadata=doc_metadata,
            section=draft.heading_path[-1] if draft.heading_path else None,
            page=draft.page_start,
            page_index=(draft.page_start - 1) if draft.page_start is not None else None,
            page_label=str(draft.page_start),
            section_path=" > ".join(draft.heading_path) or None,
            paragraph_id=draft.chunk_id,
            parent_id=draft.parent_id,
            neighbor_ids=list(draft.neighbor_ids),
            heading_path=list(draft.heading_path),
            page_end=draft.page_end,
            token_count=draft.token_count,
            content_hash=draft.content_hash,
            parser_version=draft.parser_version,
            chunker_version=draft.chunker_version,
            document_id=metadata.get("documentId"),
            version_id=metadata.get("versionId"),
            version_number=metadata.get("versionNumber"),
            release_id=metadata.get("releaseId"),
            source_type=metadata.get("sourceType"),
            source_aliases=_metadata_string_list(metadata, "sourceAliases"),
            content_state=str(metadata.get("contentState") or "ACTIVE"),
            effective_at=metadata.get("effectiveAt"),
            expires_at=metadata.get("expiresAt"),
            applicable_environments=_metadata_string_list(
                metadata,
                "applicableEnvironments",
            ),
        )
        for draft in drafts
    ]


def chunk_markdown_with_layout(
    source_path: Path,
    relative_path: str,
    chunk_size: int,
    overlap: int,
    metadata: dict[str, Any] | None = None,
) -> list[DocumentChunk]:
    return _chunk_markdown(
        source_path,
        relative_path,
        chunk_size,
        overlap,
        metadata,
        layout_chunker=chunk_layout_markdown,
    )


def load_source_chunks_with_layout(
    data_dir: Path,
    chunk_size: int,
    overlap: int,
) -> list[DocumentChunk]:
    return _load_source_chunks(
        data_dir,
        chunk_size,
        overlap,
        layout_chunker=chunk_layout_markdown,
    )
