"""Pure markdown chunking helpers for governed knowledge sources.

Layout-aware chunking (Document AI / MarkdownLayoutParser) stays in Agent
runtime. Callers that need it pass ``layout_chunker`` into ``chunk_markdown``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from knowledge_core.document_models import DocumentChunk, DocumentImage, DocumentMetadata
from knowledge_core.front_matter import parse_front_matter, strip_excluded_markdown

__all__ = [
    "DocumentChunk",
    "DocumentImage",
    "DocumentMetadata",
    "LayoutChunker",
    "chunk_markdown",
    "clean_markdown",
    "extract_images",
    "load_metadata",
    "load_source_chunks",
]

LayoutChunker = Callable[..., list[DocumentChunk]]

_SOURCE_MAP_RE = re.compile(r"<!--\s*source-map:([^>]+)-->", re.IGNORECASE)

def _coerce_date_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _metadata_string_list(metadata: dict[str, Any], field_name: str) -> list[str]:
    value = metadata.get(field_name) or []
    if not isinstance(value, list):
        raise TypeError(f"Metadata field '{field_name}' must be a list of strings.")
    return [str(item).strip() for item in value if str(item).strip()]


def _document_metadata_from_front_matter(
    front_matter: dict[str, Any],
    fallback_title: str,
) -> DocumentMetadata:
    audience = front_matter.get("audience") or []
    if not isinstance(audience, list):
        raise TypeError("Front matter 'audience' must be a list of strings.")

    version = front_matter.get("version")
    return DocumentMetadata(
        title=str(front_matter["title"]) if front_matter.get("title") else fallback_title,
        owner=str(front_matter["owner"]) if front_matter.get("owner") else None,
        category=str(front_matter["category"]) if front_matter.get("category") else None,
        version=str(version) if version is not None else None,
        effective_date=_coerce_date_value(front_matter.get("effectiveDate")),
        review_date=_coerce_date_value(front_matter.get("reviewDate")),
        audience=[str(item) for item in audience],
    )


def clean_markdown(raw_text: str) -> str:
    text = strip_excluded_markdown(raw_text)
    text = re.sub(r"«/?span[^»]*»", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_images(
    markdown: str,
    source_path: Path,
    *,
    asset_roots: list[Path] | None = None,
) -> list[DocumentImage]:
    """Collect local images referenced by Markdown.

    The corpus layout is ``sources/*.md`` beside ``sources/assets/<slug>/``.
    Release builds and older indexes may keep the same files under a sibling
    ``assets/`` directory, so extra roots are checked after the source-relative
    path misses.
    """
    roots = [(source_path.parent / "assets").resolve()]
    for root in asset_roots or []:
        resolved_root = root.resolve()
        if resolved_root not in roots:
            roots.append(resolved_root)
    images: list[DocumentImage] = []
    seen: set[str] = set()
    for alt_text, target in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", markdown):
        target_path = target.strip().split(maxsplit=1)[0].strip("<>")
        if "://" in target_path or target_path.startswith("data:"):
            continue
        located = _locate_image(source_path, target_path, roots)
        if located is None:
            continue
        resolved, relative_path = located
        if relative_path in seen:
            continue
        seen.add(relative_path)
        label = alt_text.strip() or resolved.stem
        images.append(
            DocumentImage(
                path=relative_path,
                title=label,
                alt_text=label,
            )
        )
    return images


def _locate_image(
    source_path: Path,
    target_path: str,
    asset_roots: list[Path],
) -> tuple[Path, str] | None:
    relative_ref = target_path.replace("\\", "/")
    while relative_ref.startswith("./"):
        relative_ref = relative_ref[2:]
    relative_ref = relative_ref.removeprefix("assets/")
    if not _is_safe_relative_asset(relative_ref):
        return None
    candidates = [(source_path.parent / target_path).resolve()]
    if relative_ref:
        candidates.extend((root / relative_ref).resolve() for root in asset_roots)
    for resolved in candidates:
        if not resolved.is_file() or resolved.suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
        }:
            continue
        for root in asset_roots:
            try:
                return resolved, resolved.relative_to(root).as_posix()
            except ValueError:
                continue
    return None


def _is_safe_relative_asset(relative_ref: str) -> bool:
    if not relative_ref or relative_ref.startswith(("/", "\\")):
        return False
    parts = PurePosixPath(relative_ref.replace("\\", "/")).parts
    return bool(parts) and ".." not in parts


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = max(
                text.rfind("\n\n", start, end),
                text.rfind("。", start, end),
                text.rfind("\n", start, end),
            )
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_markdown(
    source_path: Path,
    relative_path: str,
    chunk_size: int,
    overlap: int,
    metadata: dict[str, Any] | None = None,
    *,
    layout_chunker: LayoutChunker | None = None,
) -> list[DocumentChunk]:
    raw_text = source_path.read_text(encoding="utf-8")
    front_matter, body_text = parse_front_matter(raw_text)
    canonical_markdown = strip_excluded_markdown(body_text)
    text = clean_markdown(canonical_markdown)
    title_match = re.search(r"(?m)^#\s+(.+)$", text)
    derived_title = title_match.group(1).strip() if title_match else source_path.stem

    doc_metadata = (
        _document_metadata_from_front_matter(front_matter, derived_title) if front_matter else None
    )
    title = doc_metadata.title if doc_metadata and doc_metadata.title else derived_title
    metadata = metadata or {}

    allowed_groups = list(metadata.get("allowedGroups", []))
    if not allowed_groups and doc_metadata and doc_metadata.audience:
        # "all-employees" is the open/no-restriction marker, matching the
        # existing "empty allowed_groups = visible to all" convention.
        allowed_groups = [group for group in doc_metadata.audience if group != "all-employees"]
    needs_layout = bool(
        metadata.get("chunkingProfile")
        or re.search(r"(?m)^##\s+Page\s+\d+\s*$", canonical_markdown)
        or _SOURCE_MAP_RE.search(canonical_markdown)
    )
    if needs_layout and layout_chunker is not None:
        return layout_chunker(
            source_path=source_path,
            relative_path=relative_path,
            canonical_markdown=canonical_markdown,
            title=title,
            metadata=metadata,
            allowed_groups=allowed_groups,
            doc_metadata=doc_metadata,
        )

    content_parts = _section_content_parts(
        canonical_markdown=canonical_markdown,
        source_path=source_path,
        derived_title=derived_title,
        cleaned_text=text,
        chunk_size=chunk_size,
        overlap=overlap,
    )
    return _chunks_from_content_parts(
        content_parts,
        title=title,
        relative_path=relative_path,
        metadata=metadata,
        allowed_groups=allowed_groups,
        doc_metadata=doc_metadata,
    )


def _section_content_parts(
    *,
    canonical_markdown: str,
    source_path: Path,
    derived_title: str,
    cleaned_text: str,
    chunk_size: int,
    overlap: int,
) -> list[tuple[str, list[DocumentImage]]]:
    # Split markdown on #{1,3} except visual evidence headings so subheadings
    # and FAQ sections become independent retrieval chunks without cross-section contamination.
    sections = re.split(
        r"(?m)(?=^#{1,2}\s+|^###\s+(?!Visual\b|Image\b|附圖\b))",
        canonical_markdown,
    )
    content_parts: list[tuple[str, list[DocumentImage]]] = []
    for raw_section in sections:
        raw_section = raw_section.strip()
        section = clean_markdown(raw_section)
        if not section or section == f"# {derived_title}":
            continue
        images = extract_images(raw_section, source_path)
        content_parts.extend(
            (part, images) for part in _split_long_text(section, chunk_size, overlap)
        )
    if content_parts:
        return content_parts
    images = extract_images(canonical_markdown, source_path)
    return [(part, images) for part in _split_long_text(cleaned_text, chunk_size, overlap)]


def _chunks_from_content_parts(
    content_parts: list[tuple[str, list[DocumentImage]]],
    *,
    title: str,
    relative_path: str,
    metadata: dict[str, Any],
    allowed_groups: list[str],
    doc_metadata: DocumentMetadata | None,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for index, (content, images) in enumerate(content_parts):
        digest = hashlib.sha256(
            (
                f"{relative_path}:{index}:{content}:" + ",".join(image.path for image in images)
            ).encode()
        ).hexdigest()[:20]
        source_map = _parse_source_map_marker(content)
        cleaned = _strip_source_map_marker(content)
        heading_match = re.search(r"(?m)^#{1,3}\s+(.+)$", cleaned)
        section_path = source_map.get("section_path") or (
            heading_match.group(1).strip() if heading_match else None
        )
        page_index = source_map.get("page_index")
        page_label = source_map.get("page_label")
        chunks.append(
            DocumentChunk(
                chunk_id=digest,
                title=title,
                source_path=relative_path,
                content=cleaned,
                classification=str(metadata.get("classification", "internal")),
                allowed_groups=allowed_groups,
                images=images,
                metadata=doc_metadata,
                section=section_path,
                page=page_index,
                page_index=page_index,
                page_label=page_label,
                section_path=section_path,
                paragraph_id=f"p-{index + 1}",
                bbox=source_map.get("bbox"),
                coordinate_system=source_map.get("coordinate_system"),
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
        )
    return chunks


def _parse_source_map_marker(content: str) -> dict[str, Any]:
    match = _SOURCE_MAP_RE.search(content or "")
    if not match:
        return {}
    attrs = dict(re.findall(r"(\w+)=([^\s]+)", match.group(1)))
    result: dict[str, Any] = {}
    if "page_index" in attrs:
        try:
            result["page_index"] = int(attrs["page_index"])
        except ValueError:
            pass
    if "page_label" in attrs:
        result["page_label"] = attrs["page_label"]
    if "section_path" in attrs:
        result["section_path"] = attrs["section_path"].replace("_", " ")
    if "coordinate_system" in attrs:
        result["coordinate_system"] = attrs["coordinate_system"]
    if "bbox" in attrs:
        try:
            result["bbox"] = [float(part) for part in attrs["bbox"].split(",")]
        except ValueError:
            pass
    return result


def _strip_source_map_marker(content: str) -> str:
    return _SOURCE_MAP_RE.sub("", content or "").strip()


def load_metadata(data_dir: Path) -> dict[str, dict[str, Any]]:
    metadata_path = data_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    value = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("data/metadata.json must be a JSON object.")
    return {str(key): item for key, item in value.items() if isinstance(item, dict)}


def load_source_chunks(
    data_dir: Path,
    chunk_size: int,
    overlap: int,
    *,
    layout_chunker: LayoutChunker | None = None,
) -> list[DocumentChunk]:
    sources_dir = data_dir / "sources"
    if not sources_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {sources_dir}")

    metadata = load_metadata(data_dir)
    chunks: list[DocumentChunk] = []
    for source_path in sorted(sources_dir.glob("*.md")):
        if source_path.name.upper() == "README.MD":
            continue
        relative_path = source_path.relative_to(data_dir).as_posix()
        chunks.extend(
            chunk_markdown(
                source_path,
                relative_path,
                chunk_size,
                overlap,
                metadata.get(relative_path),
                layout_chunker=layout_chunker,
            )
        )
    return chunks
