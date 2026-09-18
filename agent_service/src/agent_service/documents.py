"""Compatibility facade for document chunk types and markdown chunking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_core.document_chunks import (
    DocumentChunk,
    DocumentImage,
    DocumentMetadata,
    clean_markdown,
    extract_images,
    load_metadata,
)
from knowledge_core.front_matter import parse_front_matter, strip_excluded_markdown
from knowledge_core.layout_source_chunks import (
    chunk_markdown_with_layout,
    load_source_chunks_with_layout,
)

__all__ = [
    "DocumentChunk",
    "DocumentImage",
    "DocumentMetadata",
    "chunk_markdown",
    "clean_markdown",
    "extract_images",
    "load_metadata",
    "load_source_chunks",
    "parse_front_matter",
    "strip_excluded_markdown",
]


def chunk_markdown(
    source_path: Path,
    relative_path: str,
    chunk_size: int,
    overlap: int,
    metadata: dict[str, Any] | None = None,
) -> list[DocumentChunk]:
    return chunk_markdown_with_layout(
        source_path,
        relative_path,
        chunk_size,
        overlap,
        metadata,
    )


def load_source_chunks(
    data_dir: Path,
    chunk_size: int,
    overlap: int,
) -> list[DocumentChunk]:
    return load_source_chunks_with_layout(data_dir, chunk_size, overlap)
