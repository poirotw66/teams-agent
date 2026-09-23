"""Release directory loading helpers for source trace resolution."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from knowledge_core.source_resolution import _manifest_by_key

__all__ = [
    "SAFE_RELEASE_ID",
    "SOURCE_EVENTS",
    "ReleaseLoad",
    "active_release_id",
    "list_release_ids",
    "load_release",
]

SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
SOURCE_EVENTS = frozenset({"knowledge.retrieved", "knowledge.answered"})
ReleaseLoad = tuple[
    Path,
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]


def active_release_id(releases_dir: Path) -> str | None:
    pointer = releases_dir / "active_release.json"
    if not pointer.is_file():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = payload.get("releaseId") or payload.get("release_id")
    return str(value) if value else None


def list_release_ids(releases_dir: Path, preferred: str | None = None) -> list[str]:
    values: list[str] = []
    for value in (preferred, active_release_id(releases_dir)):
        if value and SAFE_RELEASE_ID.fullmatch(value) and value not in values:
            values.append(value)
    if releases_dir.is_dir():
        for path in sorted(releases_dir.iterdir(), reverse=True):
            if path.is_dir() and SAFE_RELEASE_ID.fullmatch(path.name):
                if path.name not in values:
                    values.append(path.name)
    return values


def load_release(
    releases_dir: Path,
    release_id: str,
    release_cache: dict[str, tuple[int, int, ReleaseLoad]],
) -> ReleaseLoad | None:
    if not SAFE_RELEASE_ID.fullmatch(release_id):
        return None
    releases_root = releases_dir.expanduser().resolve()
    release_root = (releases_root / release_id).resolve()
    try:
        release_root.relative_to(releases_root)
    except ValueError:
        return None
    index_path = release_root / "index" / "chunks.json"
    if not index_path.is_file():
        release_cache.pop(release_id, None)
        return None
    try:
        stat = index_path.stat()
        cache_key = (stat.st_mtime_ns, stat.st_size)
        cached = release_cache.get(release_id)
        if cached is not None and cached[:2] == cache_key:
            return cached[2]
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        release_cache.pop(release_id, None)
        return None
    chunks = [item for item in payload.get("chunks", []) if isinstance(item, dict)]
    by_id, by_title = _manifest_by_key(release_root)
    loaded: ReleaseLoad = (release_root, chunks, by_id, by_title)
    release_cache[release_id] = (cache_key[0], cache_key[1], loaded)
    return loaded
