from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from knowledge_portal.models import PortalActor
from knowledge_portal.repository import build_repository
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


@pytest.fixture
def portal_service(tmp_path: Path) -> tuple[PortalService, PortalSettings]:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "vpn-lockout.md").write_text(
        """---
title: VPN 密碼被鎖定
owner: IT Service Desk
effectiveDate: 2026-01-01
reviewDate: 2026-12-31
audience:
  - all-employees
---

# VPN 密碼被鎖定

連續輸入錯誤 5 次會鎖定 30 分鐘。
""",
        encoding="utf-8",
    )
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "state_path", tmp_path / "portal_state.json")
    object.__setattr__(settings, "data_dir", tmp_path)
    service = PortalService(settings, build_repository(settings))
    return service, settings


@pytest.mark.asyncio
async def test_bootstrap_release_0001_creates_active_release(
    portal_service: tuple[PortalService, PortalSettings],
) -> None:
    service, settings = portal_service
    sources = settings.data_dir / "sources"
    actor = PortalActor(
        user_id="platform.demo",
        display_name="Platform Demo",
        role="PLATFORM",
        owner_unit_ids=["IT Service Desk"],
    )
    release = await service.bootstrap_release_0001(
        actor,
        sources,
        correlation_id=uuid.uuid4().hex,
        release_id="release-0001",
    )
    assert release.release_id == "release-0001"
    assert release.status == "ACTIVE"
    assert len(release.manifest) == 1
    assert (settings.release_artifact_dir / "release-0001" / "manifest.json").exists()
    assert (settings.release_artifact_dir / "active_release.json").exists()


@pytest.mark.asyncio
async def test_sync_from_local_corpus_copies_bundled_index(
    portal_service: tuple[PortalService, PortalSettings],
) -> None:
    service, settings = portal_service
    sources = settings.data_dir / "sources"
    bundled = settings.data_dir / "index" / "chunks.json"
    bundled.parent.mkdir(parents=True, exist_ok=True)
    bundled.write_text(
        '{"version":1,"embeddingModel":"test","chunks":[{"chunk_id":"c1","title":"VPN 密碼被鎖定","source_path":"sources/vpn-lockout.md","content":"test","classification":"internal","allowed_groups":[],"images":[]}]}',
        encoding="utf-8",
    )
    actor = PortalActor(
        user_id="platform.demo",
        display_name="Platform Demo",
        role="PLATFORM",
        owner_unit_ids=["IT Service Desk"],
    )
    await service.sync_from_local_corpus(
        actor,
        sources,
        correlation_id=uuid.uuid4().hex,
        bundled_index_path=bundled,
    )
    release_index = settings.release_artifact_dir / "release-0001" / "index" / "chunks.json"
    assert release_index.read_text(encoding="utf-8") == bundled.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_bootstrap_release_0001_persists_file_repository(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "helpdesk.md").write_text(
        """---
title: Helpdesk Hours
owner: IT Service Desk
effectiveDate: 2026-01-01
reviewDate: 2026-12-31
audience:
  - all-employees
---

# Helpdesk Hours

Weekdays 09:00-18:00.
""",
        encoding="utf-8",
    )
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "repository_mode", "FILE")
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "state_path", tmp_path / "portal_state" / "portal_state.json")
    object.__setattr__(settings, "data_dir", tmp_path)

    service_a = PortalService(settings, build_repository(settings))
    actor = PortalActor(
        user_id="platform.demo",
        display_name="Platform Demo",
        role="PLATFORM",
        owner_unit_ids=["IT Service Desk"],
    )
    await service_a.bootstrap_release_0001(
        actor,
        sources,
        correlation_id=uuid.uuid4().hex,
    )

    service_b = PortalService(settings, build_repository(settings))
    active_release_id = await service_b._repository.get_active_release_id()
    assert active_release_id == "release-0001"
