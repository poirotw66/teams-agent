from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import unquote

ALLOWED_IMAGE_SUFFIXES: set[str] = {".png", ".jpg", ".jpeg", ".gif"}
# Markdown destinations may contain balanced parentheses in document titles.
# Supporting one nesting level covers generated asset paths without accepting
# an unbounded expression that can backtrack on untrusted document content.
_IMAGE_REF_PATTERN: re.Pattern[str] = re.compile(r"!\[([^\]]*)\]\(((?:[^()]|\([^()]*\))*)\)")


def normalize_markdown_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.strip("<>")


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


def _directory_has_images(path: Path) -> bool:
    return any(
        item.is_file() and item.suffix.lower() in ALLOWED_IMAGE_SUFFIXES for item in path.rglob("*")
    )


def _copy_image_dir(source: Path, target: Path) -> bool:
    if not source.is_dir() or not _directory_has_images(source):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return True


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


def is_expected_asset_markdown_path(
    target_path: str,
    *,
    asset_slug: str,
    filename: str,
) -> bool:
    """Return True when the markdown image target matches assets/<slug>/<file>."""
    normalized = unquote(target_path.replace("\\", "/")).strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    expected = f"assets/{asset_slug}/{filename}"
    if normalized == expected:
        return True
    # Accept equivalent paths when only the final filename is compared under assets/<slug>/.
    parts = [part for part in normalized.split("/") if part and part != "."]
    return (
        len(parts) >= 3
        and parts[0] == "assets"
        and parts[1] == asset_slug
        and parts[-1] == filename
    )


def validate_asset_bundle(
    markdown_content: str,
    *,
    asset_slug: str,
    assets_root: Path,
) -> list[tuple[str, str, str]]:
    issues: list[tuple[str, str, str]] = []
    referenced: set[str] = set()

    for alt_text, target in _IMAGE_REF_PATTERN.findall(markdown_content):
        target_path = normalize_markdown_target(target)
        if "://" in target_path or target_path.startswith("data:"):
            continue
        filename = Path(target_path.replace("\\", "/")).name
        referenced.add(filename)
        expected_root = (assets_root / asset_slug).resolve()
        if not is_expected_asset_markdown_path(
            target_path,
            asset_slug=asset_slug,
            filename=filename,
        ):
            issues.append(
                (
                    "ASSET_PATH_UNEXPECTED",
                    "WARNING",
                    f"圖片路徑建議使用 assets/{asset_slug}/{filename}（目前為 {target_path}）",
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
