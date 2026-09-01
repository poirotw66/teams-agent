import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Fields recognized in the YAML front matter block described in spec §9.
_FRONT_MATTER_PATTERN = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)
_KNOWN_FRONT_MATTER_KEYS = {
    "title",
    "owner",
    "version",
    "effectiveDate",
    "reviewDate",
    "audience",
}


@dataclass(frozen=True)
class DocumentImage:
    path: str
    title: str
    alt_text: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DocumentImage":
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
    version: str | None = None
    effective_date: str | None = None
    review_date: str | None = None
    audience: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DocumentMetadata":
        audience = value.get("audience") or []
        if not isinstance(audience, list):
            audience = [audience]
        return cls(
            title=value.get("title"),
            owner=value.get("owner"),
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DocumentChunk":
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
        return cls(**normalized)


def _coerce_date_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def parse_front_matter(raw_text: str) -> tuple[dict[str, Any], str]:
    """Split optional leading YAML front matter from the document body.

    Returns a tuple of (front_matter_dict, remaining_body_text). Documents
    without a leading ``---`` delimited block return an empty dict and the
    original text untouched, preserving current behaviour.
    """
    match = _FRONT_MATTER_PATTERN.match(raw_text)
    if not match:
        return {}, raw_text

    block = match.group(1)
    body = raw_text[match.end() :]
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML front matter: {exc}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise TypeError("Front matter must be a YAML mapping.")

    unknown_keys = set(data) - _KNOWN_FRONT_MATTER_KEYS
    if unknown_keys:
        raise ValueError(f"Unknown front matter field(s): {', '.join(sorted(unknown_keys))}")

    return data, body


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
        version=str(version) if version is not None else None,
        effective_date=_coerce_date_value(front_matter.get("effectiveDate")),
        review_date=_coerce_date_value(front_matter.get("reviewDate")),
        audience=[str(item) for item in audience],
    )


def _strip_excluded_markdown(raw_text: str) -> str:
    text = re.sub(
        r"(?ms)^## Archive metadata.*?^---\s*$",
        "",
        raw_text,
        count=1,
    )
    return re.split(
        r"(?m)^## Limitations / Gaps\s*$",
        text,
        maxsplit=1,
    )[0]


def clean_markdown(raw_text: str) -> str:
    text = _strip_excluded_markdown(raw_text)
    text = re.sub(r"«/?span[^»]*»", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_images(
    markdown: str,
    source_path: Path,
) -> list[DocumentImage]:
    assets_dir = (source_path.parent.parent / "assets").resolve()
    images: list[DocumentImage] = []
    seen: set[str] = set()
    for alt_text, target in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", markdown):
        target_path = target.strip().split(maxsplit=1)[0].strip("<>")
        if "://" in target_path or target_path.startswith("data:"):
            continue
        resolved = (source_path.parent / target_path).resolve()
        try:
            relative_path = resolved.relative_to(assets_dir).as_posix()
        except ValueError:
            continue
        if (
            relative_path in seen
            or not resolved.is_file()
            or resolved.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif"}
        ):
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
) -> list[DocumentChunk]:
    raw_text = source_path.read_text(encoding="utf-8")
    front_matter, body_text = parse_front_matter(raw_text)
    canonical_markdown = _strip_excluded_markdown(body_text)
    text = clean_markdown(canonical_markdown)
    title_match = re.search(r"(?m)^#\s+(.+)$", text)
    derived_title = title_match.group(1).strip() if title_match else source_path.stem

    doc_metadata = (
        _document_metadata_from_front_matter(front_matter, derived_title)
        if front_matter
        else None
    )
    title = doc_metadata.title if doc_metadata and doc_metadata.title else derived_title
    metadata = metadata or {}

    allowed_groups = list(metadata.get("allowedGroups", []))
    if not allowed_groups and doc_metadata and doc_metadata.audience:
        # "all-employees" is the open/no-restriction marker, matching the
        # existing "empty allowed_groups = visible to all" convention.
        allowed_groups = [
            group for group in doc_metadata.audience if group != "all-employees"
        ]

    # Keep level-three headings with their parent page/section so screenshots and
    # the instructions they illustrate remain in the same retrieval chunk.
    sections = re.split(r"(?m)(?=^#{1,2}\s+)", canonical_markdown)
    content_parts: list[tuple[str, list[DocumentImage]]] = []
    for raw_section in sections:
        raw_section = raw_section.strip()
        section = clean_markdown(raw_section)
        if not section or section == f"# {derived_title}":
            continue
        images = extract_images(raw_section, source_path)
        content_parts.extend(
            (part, images)
            for part in _split_long_text(section, chunk_size, overlap)
        )

    if not content_parts:
        images = extract_images(canonical_markdown, source_path)
        content_parts = [
            (part, images)
            for part in _split_long_text(text, chunk_size, overlap)
        ]

    chunks: list[DocumentChunk] = []
    for index, (content, images) in enumerate(content_parts):
        digest = hashlib.sha256(
            (
                f"{relative_path}:{index}:{content}:"
                + ",".join(image.path for image in images)
            ).encode()
        ).hexdigest()[:20]
        chunks.append(
            DocumentChunk(
                chunk_id=digest,
                title=title,
                source_path=relative_path,
                content=content,
                classification=str(metadata.get("classification", "internal")),
                allowed_groups=allowed_groups,
                images=images,
                metadata=doc_metadata,
            )
        )
    return chunks


def load_metadata(data_dir: Path) -> dict[str, dict[str, Any]]:
    metadata_path = data_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    value = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("data/metadata.json must be a JSON object.")
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, dict)
    }


def load_source_chunks(
    data_dir: Path,
    chunk_size: int,
    overlap: int,
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
            )
        )
    return chunks
