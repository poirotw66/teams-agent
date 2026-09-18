"""Pure markdown/filename helpers for draft asset packaging.

Separated from ``DraftAssetStore`` so storage I/O and markdown rewrite rules
can evolve independently while callers keep importing via ``draft_assets``.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from knowledge_core.front_matter import parse_front_matter

from .asset_validation import (
    _IMAGE_REF_PATTERN,
    ALLOWED_IMAGE_SUFFIXES,
    normalize_markdown_target,
)

_UNSAFE_SLUG_CHARS = re.compile(r'[\\/:*?"<>|]+')

__all__ = [
    "markdown_asset_ref",
    "markdown_image_references",
    "normalize_upload_filename",
    "parse_markdown_import",
    "referenced_asset_filenames",
    "referenced_asset_relative_paths",
    "rewrite_local_image_refs",
    "slug_from_title",
    "title_from_filename",
]


def slug_from_title(title: str) -> str:
    slug = _UNSAFE_SLUG_CHARS.sub("-", title.strip()).strip("-")
    return slug[:80] or "document"


def normalize_upload_filename(name: str) -> str:
    candidate = Path(name).name.strip()
    if not candidate or candidate in {".", ".."}:
        raise ValueError("Invalid file name.")
    if ".." in candidate or "/" in candidate or "\\" in candidate:
        raise ValueError("File name must not contain path separators.")
    return candidate


def title_from_filename(filename: str | None) -> str:
    if not filename:
        return ""
    stem = Path(normalize_upload_filename(filename)).stem.strip()
    return stem


def parse_markdown_import(
    raw: str,
    *,
    default_owner_unit_id: str,
    filename: str | None = None,
) -> dict[str, object]:
    front_matter, body = parse_front_matter(raw)
    raw_title = front_matter.get("title")
    if raw_title and str(raw_title).strip():
        title = str(raw_title).strip()
    else:
        title = title_from_filename(filename) or "Untitled"
    owner = str(front_matter.get("owner") or default_owner_unit_id)
    effective_at = str(front_matter.get("effectiveDate") or "2026-01-01")
    review_due_at = str(front_matter.get("reviewDate") or "2026-12-31")
    audience_raw = front_matter.get("audience") or ["all-employees"]
    if not isinstance(audience_raw, list):
        audience_raw = [audience_raw]
    audience_values = [str(item) for item in audience_raw]
    if "all-employees" in audience_values:
        audience_type = "ALL_EMPLOYEES"
        audience_group_ids: list[str] = []
    else:
        audience_type = "RESTRICTED_GROUPS"
        audience_group_ids = audience_values
    markdown_content = body.strip() or raw.strip()
    return {
        "title": title,
        "owner_unit_id": owner,
        "effective_at": effective_at,
        "review_due_at": review_due_at,
        "audience_type": audience_type,
        "audience_group_ids": audience_group_ids,
        "markdown_content": markdown_content,
        "asset_slug": slug_from_title(title),
    }


def referenced_asset_filenames(markdown_content: str, asset_slug: str) -> set[str]:
    filenames: set[str] = set()
    for _, target in markdown_image_references(markdown_content):
        target_path = normalize_markdown_target(target)
        if "://" in target_path or target_path.startswith("data:"):
            continue
        normalized = target_path.replace("\\", "/")
        filenames.add(Path(normalized).name)
    return filenames


def referenced_asset_relative_paths(markdown_content: str) -> set[str]:
    """Return corpus-relative image paths cited by markdown (``folder/file.png``).

    Titles may slug to a different folder than historical corpus assets, so
    packaging must follow the path embedded in the markdown, not only
    ``slug_from_title``.
    """
    paths: set[str] = set()
    for _, target in markdown_image_references(markdown_content):
        target_path = normalize_markdown_target(target)
        if "://" in target_path or target_path.startswith("data:"):
            continue
        normalized = target_path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        relative = normalized.removeprefix("assets/")
        if not relative or relative.startswith("/") or ".." in PurePosixPath(relative).parts:
            continue
        if Path(relative).suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
            continue
        paths.add(relative)
    return paths


def markdown_image_references(markdown_content: str) -> list[tuple[str, str]]:
    return [
        (alt_text.strip(), normalize_markdown_target(target))
        for alt_text, target in _IMAGE_REF_PATTERN.findall(markdown_content)
    ]


def markdown_asset_ref(*, asset_slug: str, filename: str, alt_text: str = "") -> str:
    alt = alt_text.strip()
    return f"![{alt}](assets/{asset_slug}/{filename})"


def rewrite_local_image_refs(markdown_content: str, *, asset_slug: str) -> str:
    """Normalize local image refs to assets/<slug>/<filename> for draft validation."""

    def _replace(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        target_path = normalize_markdown_target(match.group(2))
        if "://" in target_path or target_path.startswith("data:"):
            return match.group(0)
        filename = Path(target_path.replace("\\", "/")).name
        if not filename:
            return match.group(0)
        return markdown_asset_ref(
            asset_slug=asset_slug,
            filename=filename,
            alt_text=alt_text,
        )

    return _IMAGE_REF_PATTERN.sub(_replace, markdown_content)
