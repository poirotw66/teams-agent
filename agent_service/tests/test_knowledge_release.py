from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_service.knowledge_release import (
    read_active_release_id,
    release_index_path,
    resolve_knowledge_index,
    write_active_release_pointer,
)
from agent_service.settings import RagSettings


def _settings(
    tmp_path: Path,
    *,
    mode: str = "AUTO",
    active_release_id: str | None = None,
    bundled_exists: bool = True,
) -> RagSettings:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    bundled = data_dir / "index" / "chunks.json"
    if bundled_exists:
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_text('{"version":1,"embeddingModel":null,"chunks":[]}', encoding="utf-8")
    return RagSettings(
        data_dir=data_dir,
        index_path=bundled,
        auto_build_index=False,
        knowledge_release_mode=mode,
        knowledge_release_dir=tmp_path / "releases",
        knowledge_active_release_id=active_release_id,
    )


def test_resolve_knowledge_index_prefers_portal_release(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    release_id = "release-demo"
    index_path = release_index_path(settings.knowledge_release_dir, release_id)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text('{"version":1,"embeddingModel":null,"chunks":[{"chunk_id":"1"}]}', encoding="utf-8")
    write_active_release_pointer(settings.knowledge_release_dir, release_id)

    resolved = resolve_knowledge_index(settings)
    assert resolved.release_id == release_id
    assert resolved.source == "portal_release"
    assert resolved.index_path == index_path


def test_resolve_knowledge_index_falls_back_to_bundled_in_auto_mode(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    resolved = resolve_knowledge_index(settings)
    assert resolved.source == "bundled_index"
    assert resolved.release_id is None


def test_portal_mode_requires_active_release(tmp_path: Path) -> None:
    settings = _settings(tmp_path, mode="PORTAL", bundled_exists=False)
    with pytest.raises(FileNotFoundError):
        resolve_knowledge_index(settings)


def test_active_release_pointer_round_trip(tmp_path: Path) -> None:
    release_dir = tmp_path / "releases"
    write_active_release_pointer(release_dir, "release-123")
    assert read_active_release_id(release_dir) == "release-123"
    payload = json.loads((release_dir / "active_release.json").read_text(encoding="utf-8"))
    assert payload["releaseId"] == "release-123"
