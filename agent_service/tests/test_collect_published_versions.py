"""Published-version collection must not drop docs outside the active manifest."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from knowledge_portal.models import PortalActor
from knowledge_portal.release.publish import collect_active_published_versions


def _actor() -> PortalActor:
    return PortalActor(
        user_id="ops.admin",
        display_name="Admin",
        role="MANAGER",
        owner_unit_ids=["IT Service Desk"],
        tenant_id="default",
    )


def _version(document_id: str, version_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        document_id=document_id,
        version_id=version_id,
        status="PUBLISHED",
    )


@pytest.mark.asyncio
async def test_collect_includes_published_docs_missing_from_active_manifest() -> None:
    in_release = _version("doc-in-release", "ver-1")
    orphan = _version("doc-orphan", "ver-2")
    repository = SimpleNamespace(
        get_active_release_id=AsyncMock(return_value="release-current"),
        get_release=AsyncMock(
            return_value=SimpleNamespace(
                manifest=[SimpleNamespace(document_id="doc-in-release", version_id="ver-1")]
            )
        ),
        get_version=AsyncMock(
            side_effect=lambda version_id: {
                "ver-1": in_release,
                "ver-2": orphan,
            }.get(version_id)
        ),
        list_documents=AsyncMock(
            return_value=[
                SimpleNamespace(
                    document_id="doc-in-release",
                    current_published_version_id="ver-1",
                ),
                SimpleNamespace(
                    document_id="doc-orphan",
                    current_published_version_id="ver-2",
                ),
            ]
        ),
    )

    collected = await collect_active_published_versions(
        repository=repository,
        actor=_actor(),
    )

    assert {item.document_id for item in collected} == {
        "doc-in-release",
        "doc-orphan",
    }
    list_actor = repository.list_documents.await_args.kwargs["actor"]
    assert list_actor.role == "PLATFORM"
    assert list_actor.tenant_id is None
