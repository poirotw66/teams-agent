import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class DocumentChunk:
    chunk_id: str
    title: str
    source_path: str
    content: str
    classification: str = "internal"
    allowed_groups: list[str] | None = None
    vector: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DocumentChunk":
        return cls(**value)


def clean_markdown(raw_text: str) -> str:
    text = re.sub(
        r"(?ms)^## Archive metadata.*?^---\s*$",
        "",
        raw_text,
        count=1,
    )
    text = re.split(r"(?m)^## Limitations / Gaps\s*$", text, maxsplit=1)[0]
    text = re.sub(r"«/?span[^»]*»", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
    text = clean_markdown(raw_text)
    title_match = re.search(r"(?m)^#\s+(.+)$", text)
    title = title_match.group(1).strip() if title_match else source_path.stem
    metadata = metadata or {}

    sections = re.split(r"(?m)(?=^#{1,3}\s+)", text)
    content_parts: list[str] = []
    for section in sections:
        section = section.strip()
        if not section or section == f"# {title}":
            continue
        content_parts.extend(_split_long_text(section, chunk_size, overlap))

    if not content_parts:
        content_parts = _split_long_text(text, chunk_size, overlap)

    chunks: list[DocumentChunk] = []
    for index, content in enumerate(content_parts):
        digest = hashlib.sha256(
            f"{relative_path}:{index}:{content}".encode()
        ).hexdigest()[:20]
        chunks.append(
            DocumentChunk(
                chunk_id=digest,
                title=title,
                source_path=relative_path,
                content=content,
                classification=str(metadata.get("classification", "internal")),
                allowed_groups=list(metadata.get("allowedGroups", [])),
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
