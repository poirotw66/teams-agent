#!/usr/bin/env python3
"""Sync local Markdown sources and rag-index output into the knowledge portal."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_sources_dir(data_dir: Path) -> Path:
    sources = data_dir / "sources"
    if sources.is_dir() and any(
        path.suffix == ".md" and not path.name.upper().startswith("README")
        for path in sources.iterdir()
    ):
        return sources
    return _repo_root() / "data" / "sources.sample"


async def _run(
    sources_dir: Path,
    bundled_index_path: Path | None,
    release_id: str,
    reindex: bool,
) -> None:
    agent_service_dir = _repo_root() / "agent_service"
    sys.path.insert(0, str(agent_service_dir / "src"))

    from agent_service.indexer import build_index
    from agent_service.settings import RagSettings
    from knowledge_portal.models import PortalActor
    from knowledge_portal.repository import build_repository
    from knowledge_portal.service import PortalService
    from knowledge_portal.settings import PortalSettings

    rag_settings = RagSettings.from_env()
    if reindex or not rag_settings.index_path.is_file():
        print("Building local rag-index…")
        build_index(rag_settings)
    elif bundled_index_path is None:
        bundled_index_path = rag_settings.index_path

    if bundled_index_path is None:
        bundled_index_path = rag_settings.index_path
    if not bundled_index_path.is_file():
        raise SystemExit(
            f"Bundled index not found: {bundled_index_path}. Run: cd agent_service && uv run rag-index"
        )

    settings = PortalSettings.from_env()
    service = PortalService(settings, build_repository(settings))
    actor = PortalActor(
        user_id="platform.sync",
        display_name="Platform Sync",
        role="PLATFORM",
        owner_unit_ids=list(settings.default_owner_unit_ids),
    )
    release = await service.sync_from_local_corpus(
        actor,
        sources_dir,
        correlation_id=uuid.uuid4().hex,
        bundled_index_path=bundled_index_path,
        release_id=release_id,
    )
    chunk_payload = __import__("json").loads(bundled_index_path.read_text(encoding="utf-8"))
    chunk_count = len(chunk_payload.get("chunks", []))
    print("Local knowledge sync complete.")
    print(f"Sources:        {sources_dir}")
    print(f"Bundled index:  {bundled_index_path} ({chunk_count} chunks)")
    print(f"Release ID:     {release.release_id}")
    print(f"Portal docs:    {len(release.manifest)}")
    print(f"Active pointer: {settings.release_artifact_dir / 'active_release.json'}")


def main() -> None:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Sync local data/sources and data/index/chunks.json into portal release-0001."
    )
    parser.add_argument(
        "sources_dir",
        nargs="?",
        default="",
        help="Markdown sources directory (default: data/sources)",
    )
    parser.add_argument(
        "--bundled-index",
        default="",
        help="Existing rag-index path (default: RAG_INDEX_PATH / data/index/chunks.json)",
    )
    parser.add_argument(
        "--release-id",
        default="release-0001",
        help="Release identifier (default: release-0001)",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Rebuild data/index/chunks.json from sources before syncing",
    )
    args = parser.parse_args()

    data_dir = Path(
        __import__("os").environ.get("KNOWLEDGE_PORTAL_DATA_DIR", repo_root / "data")
    )
    sources_dir = Path(args.sources_dir).expanduser().resolve() if args.sources_dir else _default_sources_dir(data_dir)
    if not sources_dir.is_dir():
        raise SystemExit(f"Sources directory not found: {sources_dir}")

    bundled_index_path = (
        Path(args.bundled_index).expanduser().resolve()
        if args.bundled_index
        else None
    )
    asyncio.run(_run(sources_dir, bundled_index_path, args.release_id, args.reindex))


if __name__ == "__main__":
    main()
