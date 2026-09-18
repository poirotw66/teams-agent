"""Shared document chunk and metadata dataclasses."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

__all__ = [
    "DocumentChunk",
    "DocumentImage",
    "DocumentMetadata",
]

@dataclass(frozen=True)
class DocumentImage:
    path: str
    title: str
    alt_text: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DocumentImage:
        return cls(
            path=str(value["path"]),
            title=str(value["title"]),
            alt_text=str(value["alt_text"]),
        )


@dataclass
class DocumentMetadata:
    """Governance metadata parsed from a source document's YAML front matter."""

    title: str | None = None
    owner: str | None = None
    category: str | None = None
    version: str | None = None
    effective_date: str | None = None
    review_date: str | None = None
    audience: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DocumentMetadata:
        audience = value.get("audience") or []
        if not isinstance(audience, list):
            audience = [audience]
        return cls(
            title=value.get("title"),
            owner=value.get("owner"),
            category=value.get("category"),
            version=str(value["version"]) if value.get("version") is not None else None,
            effective_date=value.get("effective_date"),
            review_date=value.get("review_date"),
            audience=[str(item) for item in audience],
        )


@dataclass
class DocumentChunk:
    chunk_id: str
    title: str
    source_path: str
    content: str
    classification: str = "internal"
    allowed_groups: list[str] | None = None
    images: list[DocumentImage] | None = None
    vector: list[float] | None = None
    metadata: DocumentMetadata | None = None
    # Release/source identity is hydrated from the portal manifest when an
    # index is loaded.  They stay optional for bundled and legacy indexes.
    document_id: str | None = None
    version_id: str | None = None
    version_number: int | None = None
    release_id: str | None = None
    section: str | None = None
    page: int | None = None
    source_type: str | None = None
    original_asset_available: bool = False
    original_asset_name: str | None = None
    # Ingestion source-map fields for citation jump/highlight (F08).
    page_index: int | None = None
    page_label: str | None = None
    bbox: list[float] | None = None
    coordinate_system: str | None = None
    section_path: str | None = None
    paragraph_id: str | None = None
    parent_id: str | None = None
    neighbor_ids: list[str] = field(default_factory=list)
    heading_path: list[str] = field(default_factory=list)
    page_end: int | None = None
    token_count: int | None = None
    content_hash: str | None = None
    parser_version: str | None = None
    chunker_version: str | None = None
    source_aliases: list[str] = field(default_factory=list)
    content_state: str = "ACTIVE"
    effective_at: str | None = None
    expires_at: str | None = None
    applicable_environments: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DocumentChunk:
        normalized = dict(value)
        normalized["images"] = [
            DocumentImage.from_dict(item)
            for item in normalized.get("images") or []
            if isinstance(item, dict)
        ]
        if isinstance(normalized.get("metadata"), dict):
            normalized["metadata"] = DocumentMetadata.from_dict(normalized["metadata"])
        elif "metadata" in normalized:
            normalized["metadata"] = None
        known = {item.name for item in fields(cls)}
        filtered = {key: item for key, item in normalized.items() if key in known}
        return cls(**filtered)


