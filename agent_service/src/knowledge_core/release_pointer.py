"""Active knowledge-release pointer helpers shared across domains."""

from __future__ import annotations

import json
from pathlib import Path

ACTIVE_RELEASE_FILENAME = "active_release.json"

__all__ = [
    "ACTIVE_RELEASE_FILENAME",
    "read_active_release_id",
    "release_index_path",
    "write_active_release_pointer",
]


def read_active_release_id(release_dir: Path) -> str | None:
    pointer = release_dir / ACTIVE_RELEASE_FILENAME
    if not pointer.is_file():
        return None
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    release_id = payload.get("releaseId") or payload.get("release_id")
    return str(release_id) if release_id else None


def write_active_release_pointer(release_dir: Path, release_id: str | None) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    pointer = release_dir / ACTIVE_RELEASE_FILENAME
    if release_id is None:
        if pointer.exists():
            pointer.unlink()
        return
    pointer.write_text(
        json.dumps({"releaseId": release_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def release_index_path(release_dir: Path, release_id: str) -> Path:
    return release_dir / release_id / "index" / "chunks.json"
