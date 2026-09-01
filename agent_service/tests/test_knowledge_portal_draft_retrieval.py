from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_portal.draft_retrieval import evaluate_test_case, search_draft_version
from knowledge_portal.models import KnowledgeVersionRecord, ValidationSummary
from knowledge_portal.settings import PortalSettings


def _draft_version(title: str, body: str) -> KnowledgeVersionRecord:
    return KnowledgeVersionRecord(
        version_id="ver-doc-1",
        document_id="doc-vpn",
        version_number=1,
        content_hash="abc123",
        canonical_content=body,
        change_summary="Draft",
        change_reason="Testing",
        effective_at="2026-01-01",
        review_due_at="2026-12-31",
        audience_type="ALL_EMPLOYEES",
        audience_group_ids=[],
        owner_unit_id="IT Service Desk",
        title=title,
        status="DRAFT",
        validation_summary=ValidationSummary(issues=[]),
        parse_preview=None,
        etag="etag-1",
        created_at="2026-08-01T00:00:00Z",
        created_by="author.one",
    )


@pytest.fixture
def portal_settings(tmp_path: Path) -> PortalSettings:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "release_artifact_dir", tmp_path / "releases")
    object.__setattr__(settings, "data_dir", tmp_path)
    return settings


def test_search_draft_version_returns_hits(portal_settings: PortalSettings) -> None:
    version = _draft_version(
        "VPN 密碼被鎖定",
        "# VPN 密碼被鎖定\n\n連續輸入錯誤 5 次會鎖定 30 分鐘。",
    )
    result = search_draft_version(
        version=version,
        query="VPN 密碼鎖定",
        groups=[],
        settings=portal_settings,
    )
    assert result.hits
    assert result.matched_draft is True


def test_evaluate_test_case_passes_when_draft_matches(portal_settings: PortalSettings) -> None:
    version = _draft_version(
        "VPN 密碼被鎖定",
        "# VPN 密碼被鎖定\n\n連續輸入錯誤 5 次會鎖定 30 分鐘。",
    )
    status, _, cited_titles, failure_reason = evaluate_test_case(
        version=version,
        question="VPN 密碼被鎖定怎麼辦？",
        simulated_audience=[],
        settings=portal_settings,
    )
    assert status == "PASS"
    assert cited_titles
    assert failure_reason == ""
