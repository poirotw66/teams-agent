#!/usr/bin/env python3
"""Import Markdown sources into portal state and activate release-0001."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_sources_dir() -> Path:
    repo_root = _repo_root()
    sources = repo_root / "data" / "sources"
    if sources.is_dir() and any(
        path.suffix == ".md" and path.name.upper() != "README.MD"
        for path in sources.iterdir()
    ):
        return sources
    return repo_root / "data" / "sources.sample"


async def _run(sources_dir: Path, release_id: str) -> None:
    agent_service_dir = _repo_root() / "agent_service"
    sys.path.insert(0, str(agent_service_dir / "src"))

    from knowledge_portal.models import PortalActor
    from knowledge_portal.repository import build_repository
    from knowledge_portal.service import PortalService
    from knowledge_portal.settings import PortalSettings

    settings = PortalSettings.from_env()
    service = PortalService(settings, build_repository(settings))
    actor = PortalActor(
        user_id="platform.bootstrap",
        display_name="Platform Bootstrap",
        role="PLATFORM",
        owner_unit_ids=list(settings.default_owner_unit_ids),
    )
    release = await service.bootstrap_release_0001(
        actor,
        sources_dir,
        correlation_id=uuid.uuid4().hex,
        release_id=release_id,
    )
    active_pointer = settings.release_artifact_dir / "active_release.json"
    print("Bootstrap complete.")
    print(f"Release ID:     {release.release_id}")
    print(f"Documents:      {len(release.manifest)}")
    print(f"Corpus hash:    {release.corpus_hash}")
    print(f"Index artifact: {release.index_artifact_uri}")
    print(f"Active pointer: {active_pointer}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Markdown sources and activate release-0001."
    )
    parser.add_argument(
        "sources_dir",
        nargs="?",
        default=str(_default_sources_dir()),
        help="Directory containing *.md sources (default: data/sources or sources.sample)",
    )
    parser.add_argument(
        "--release-id",
        default="release-0001",
        help="Release identifier (default: release-0001)",
    )
    args = parser.parse_args()
    sources_dir = Path(args.sources_dir).expanduser().resolve()
    if not sources_dir.is_dir():
        raise SystemExit(f"Sources directory not found: {sources_dir}")
    asyncio.run(_run(sources_dir, args.release_id))


if __name__ == "__main__":
    main()
