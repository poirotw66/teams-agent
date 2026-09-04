from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from agent_service.documents import parse_front_matter

from .models import DraftAssetRecord
from .settings import PortalSettings

ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif"}
_IMAGE_REF_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_UNSAFE_SLUG_CHARS = re.compile(r'[\\/:*?"<>|]+')


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


def normalize_markdown_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.strip("<>")


def referenced_asset_filenames(markdown_content: str, asset_slug: str) -> set[str]:
    filenames: set[str] = set()
    for _, target in _IMAGE_REF_PATTERN.findall(markdown_content):
        target_path = normalize_markdown_target(target)
        if "://" in target_path or target_path.startswith("data:"):
            continue
        normalized = target_path.replace("\\", "/")
        filenames.add(Path(normalized).name)
    return filenames


def markdown_asset_ref(*, asset_slug: str, filename: str, alt_text: str = "") -> str:
    alt = alt_text.strip()
    return f"![{alt}](assets/{asset_slug}/{filename})"


@dataclass(frozen=True)
class DraftAssetStore:
    settings: PortalSettings

    @property
    def root(self) -> Path:
        return self.settings.drafts_dir

    def bundle_dir(self, document_id: str, version_id: str) -> Path:
        return self.root / document_id / version_id

    def assets_root(self, document_id: str, version_id: str) -> Path:
        return self.bundle_dir(document_id, version_id) / "assets"

    def asset_dir(self, document_id: str, version_id: str, asset_slug: str) -> Path:
        return self.assets_root(document_id, version_id) / asset_slug

    def list_assets(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
    ) -> list[DraftAssetRecord]:
        directory = self.asset_dir(document_id, version_id, asset_slug)
        if not directory.is_dir():
            return []
        items: list[DraftAssetRecord] = []
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
                continue
            payload = path.read_bytes()
            items.append(
                DraftAssetRecord(
                    filename=path.name,
                    size_bytes=len(payload),
                    content_type=_content_type(path.suffix),
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
        return items

    def save_asset(
        self,
        *,
        document_id: str,
        version_id: str,
        asset_slug: str,
        filename: str,
        payload: bytes,
    ) -> DraftAssetRecord:
        if len(payload) > self.settings.max_asset_bytes:
            raise ValueError(
                f"Image exceeds {self.settings.max_asset_bytes} bytes: {filename}"
            )
        normalized = normalize_upload_filename(filename)
        suffix = Path(normalized).suffix.lower()
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image type: {suffix or 'unknown'}")
        existing = self.list_assets(document_id, version_id, asset_slug)
        replacing = any(item.filename == normalized for item in existing)
        if not replacing and len(existing) >= self.settings.max_assets_per_version:
            raise ValueError(
                f"At most {self.settings.max_assets_per_version} images per draft."
            )
        target_dir = self.asset_dir(document_id, version_id, asset_slug)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / normalized
        target.write_bytes(payload)
        return DraftAssetRecord(
            filename=normalized,
            size_bytes=len(payload),
            content_type=_content_type(suffix),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def delete_asset(
        self,
        *,
        document_id: str,
        version_id: str,
        asset_slug: str,
        filename: str,
    ) -> None:
        target = self.asset_dir(document_id, version_id, asset_slug) / normalize_upload_filename(
            filename
        )
        if target.exists():
            target.unlink()

    def copy_bundle(
        self,
        *,
        source_document_id: str,
        source_version_id: str,
        target_document_id: str,
        target_version_id: str,
        asset_slug: str,
    ) -> None:
        source_dir = self.asset_dir(source_document_id, source_version_id, asset_slug)
        if source_dir.is_dir():
            target_dir = self.asset_dir(target_document_id, target_version_id, asset_slug)
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            return
        legacy_dir = self.settings.data_dir / "assets" / asset_slug
        if legacy_dir.is_dir():
            target_dir = self.asset_dir(target_document_id, target_version_id, asset_slug)
            target_dir.mkdir(parents=True, exist_ok=True)
            for path in legacy_dir.iterdir():
                if path.is_file() and path.suffix.lower() in ALLOWED_IMAGE_SUFFIXES:
                    shutil.copy2(path, target_dir / path.name)

    def materialize_workspace(
        self,
        workspace_root: Path,
        *,
        version,
        source_filename: str,
    ) -> None:
        sources_dir = workspace_root / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        body = version.canonical_content
        target = sources_dir / source_filename
        target.write_text(body, encoding="utf-8")
        slug = version.asset_slug or slug_from_title(version.title)
        asset_dir = self.asset_dir(version.document_id, version.version_id, slug)
        if asset_dir.is_dir():
            release_assets = workspace_root / "assets" / slug
            release_assets.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(asset_dir, release_assets)
            return
        legacy_dir = self.settings.data_dir / "assets" / slug
        if legacy_dir.is_dir():
            release_assets = workspace_root / "assets" / slug
            release_assets.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(legacy_dir, release_assets)

    def copy_assets_to_release(
        self,
        release_dir: Path,
        *,
        version,
    ) -> None:
        slug = version.asset_slug or slug_from_title(version.title)
        target_dir = release_dir / "assets" / slug
        source_dir = self.asset_dir(version.document_id, version.version_id, slug)
        if source_dir.is_dir():
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            return
        legacy_dir = self.settings.data_dir / "assets" / slug
        if legacy_dir.is_dir():
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(legacy_dir, target_dir)

    def next_filename(
        self,
        document_id: str,
        version_id: str,
        asset_slug: str,
    ) -> str:
        existing = {
            item.filename
            for item in self.list_assets(document_id, version_id, asset_slug)
        }
        index = 1
        while True:
            candidate = f"p{index:02d}.png"
            if candidate not in existing:
                return candidate
            index += 1


def asset_content_type(suffix: str) -> str:
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
    }
    return mapping.get(suffix.lower(), "application/octet-stream")


def _content_type(suffix: str) -> str:
    return asset_content_type(suffix)


def resolve_local_asset_path(
    markdown_content: str,
    *,
    source_path: Path,
    asset_slug: str,
    assets_root: Path,
) -> Path | None:
    for _, target in _IMAGE_REF_PATTERN.findall(markdown_content):
        target_path = normalize_markdown_target(target)
        if "://" in target_path or target_path.startswith("data:"):
            continue
        resolved = (source_path.parent / target_path).resolve()
        try:
            resolved.relative_to(assets_root.resolve())
        except ValueError:
            expected = assets_root / asset_slug / Path(target_path).name
            if expected.is_file():
                return expected
            continue
        if resolved.is_file():
            return resolved
    return None


def validate_asset_bundle(
    markdown_content: str,
    *,
    asset_slug: str,
    assets_root: Path,
) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    referenced: set[str] = set()
    source_path = Path("sources/document.md")

    for alt_text, target in _IMAGE_REF_PATTERN.findall(markdown_content):
        target_path = normalize_markdown_target(target)
        if "://" in target_path or target_path.startswith("data:"):
            continue
        filename = Path(target_path.replace("\\", "/")).name
        referenced.add(filename)
        resolved = (source_path.parent / target_path).resolve()
        expected_root = (assets_root / asset_slug).resolve()
        try:
            resolved.relative_to(expected_root.parent)
        except ValueError:
            issues.append(
                (
                    "ASSET_PATH_UNEXPECTED",
                    "WARNING",
                    f"圖片路徑建議使用 assets/{asset_slug}/：{target_path}",
                )
            )
        candidate = expected_root / filename
        if not candidate.is_file():
            issues.append(
                (
                    "MISSING_ASSET",
                    "BLOCKING",
                    f"正文引用的圖片尚未上傳：{filename}",
                )
            )
        if not alt_text.strip():
            issues.append(
                (
                    "MISSING_ALT_TEXT",
                    "WARNING",
                    f"圖片建議填寫替代文字：{filename}",
                )
            )

    asset_dir = assets_root / asset_slug
    if asset_dir.is_dir():
        for path in asset_dir.iterdir():
            if path.is_file() and path.name not in referenced:
                issues.append(
                    (
                        "ORPHAN_ASSET",
                        "WARNING",
                        f"已上傳的圖片未在正文中引用：{path.name}",
                    )
                )
    return issues
