from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .settings import RagSettings

logger = logging.getLogger(__name__)

ACTIVE_RELEASE_FILENAME = "active_release.json"


@dataclass(frozen=True)
class ResolvedKnowledgeIndex:
    index_path: Path
    release_id: str | None
    source: str


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


def resolve_knowledge_index(settings: RagSettings) -> ResolvedKnowledgeIndex:
    mode = settings.knowledge_release_mode.upper()
    if mode not in {"BUNDLED", "PORTAL", "AUTO"}:
        raise ValueError("KNOWLEDGE_RELEASE_MODE must be BUNDLED, PORTAL, or AUTO.")

    release_dir = settings.knowledge_release_dir or (settings.data_dir / "releases")
    explicit_release_id = settings.knowledge_active_release_id
    pointer_release_id = read_active_release_id(release_dir)
    release_id = explicit_release_id or pointer_release_id

    if release_id:
        candidate = release_index_path(release_dir, release_id)
        if candidate.is_file():
            logger.info(
                "Loading knowledge index from portal release %s at %s",
                release_id,
                candidate,
            )
            return ResolvedKnowledgeIndex(
                index_path=candidate,
                release_id=release_id,
                source="portal_release",
            )
        if mode == "PORTAL":
            raise FileNotFoundError(
                f"Active knowledge release index not found: {candidate}"
            )
        logger.warning(
            "Active release %s was configured but index file is missing: %s",
            release_id,
            candidate,
        )

    if mode == "PORTAL":
        raise FileNotFoundError(
            "KNOWLEDGE_RELEASE_MODE=PORTAL requires an active portal release index."
        )

    bundled = settings.index_path
    if bundled.is_file():
        return ResolvedKnowledgeIndex(
            index_path=bundled,
            release_id=None,
            source="bundled_index",
        )

    if mode == "BUNDLED" or not settings.auto_build_index:
        raise FileNotFoundError(f"RAG index not found: {bundled}")

    return ResolvedKnowledgeIndex(
        index_path=bundled,
        release_id=None,
        source="auto_build",
    )
