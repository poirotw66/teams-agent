"""Tests for signed knowledge-source citation links."""

from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from teams_agent.cards import build_agent_activity
from teams_agent.contracts import AgentResponse, Citation, format_agent_response
from teams_agent.settings import AgentSettings
from teams_agent.source_links import (
    CitationViewerContext,
    build_source_url,
    enrich_citation_urls,
    resolve_source_file,
    sign_source_access,
)
from teams_agent.viewer_sessions import InMemoryViewerMembershipStore


def _settings(tmp_path: Path) -> AgentSettings:
    source_dir = tmp_path / "data"
    sources = source_dir / "sources"
    sources.mkdir(parents=True)
    (sources / "大州系統_功能無法點選.md").write_text("# 大州\n步驟", encoding="utf-8")
    return AgentSettings(
        source_dir=source_dir,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
        asset_url_ttl_seconds=3600,
    )


def _viewer() -> CitationViewerContext:
    return CitationViewerContext(subject="user-1", groups=("it-helpdesk",), tenant_id="t1")


def test_enrich_citation_urls_fills_missing_url_from_source_path(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    response = AgentResponse(
        answer="請調整安全性設定。",
        traceId="trace-1",
        citations=[
            Citation(
                title="大州系統_功能無法點選",
                sourcePath="sources/大州系統_功能無法點選.md",
                sourceRefId="src-abc",
            )
        ],
    )

    enriched = enrich_citation_urls(
        response, settings, now=1_000, viewer=_viewer(), membership_store=store
    )

    assert enriched.citations[0].url is not None
    assert enriched.citations[0].url.startswith(
        "https://bot.example.com/rag-sources/sources/"
    )
    assert "subject=user-1" in enriched.citations[0].url
    assert "groups=" not in enriched.citations[0].url
    assert "signature=" in enriched.citations[0].url


def test_enrich_without_viewer_does_not_mint_transferable_url(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    response = AgentResponse(
        answer="ok",
        traceId="t",
        citations=[Citation(title="Doc", sourcePath="sources/大州系統_功能無法點選.md")],
    )
    enriched = enrich_citation_urls(response, settings, now=1_000, viewer=None)
    assert enriched.citations[0].url is None


def test_enrich_citation_urls_keeps_existing_formal_url(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    response = AgentResponse(
        answer="ok",
        traceId="trace-1",
        citations=[
            Citation(
                title="API Key",
                url="https://internal.example/docs/api-key",
                sourcePath="sources/api.md",
            )
        ],
    )

    enriched = enrich_citation_urls(
        response, settings, now=1_000, viewer=_viewer()
    )

    assert enriched.citations[0].url == "https://internal.example/docs/api-key"


def test_build_agent_activity_renders_clickable_source_link(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    response = AgentResponse(
        answer="請調整安全性設定。",
        traceId="trace-1",
        citations=[
            Citation(
                title="大州系統_功能無法點選",
                sourcePath="sources/大州系統_功能無法點選.md",
            )
        ],
    )

    activity = build_agent_activity(
        response, settings, now=1_000, viewer=_viewer()
    )
    assert isinstance(activity, str)
    assert "[大州系統_功能無法點選](https://bot.example.com/rag-sources/" in activity


def test_resolve_source_file_serves_markdown(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    url = build_source_url(
        "sources/大州系統_功能無法點選.md",
        settings,
        now=1_000,
        viewer=_viewer(),
        membership_store=store,
    )
    assert url is not None
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    resolved = resolve_source_file(
        "sources/大州系統_功能無法點選.md",
        params["expires"][0],
        params["signature"][0],
        settings,
        now=1_000,
        subject=params["subject"][0],
        groups="forged-vip",
        source_ref_id=(params.get("sourceRefId") or [None])[0],
        tenant_id=(params.get("tenantId") or [None])[0],
        membership_store=store,
    )
    assert resolved.read_text(encoding="utf-8").startswith("# 大州")


def test_foreign_subject_cannot_open_signed_source(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    url = build_source_url(
        "sources/大州系統_功能無法點選.md",
        settings,
        now=1_000,
        viewer=_viewer(),
        membership_store=store,
    )
    assert url is not None
    params = parse_qs(urlparse(url).query)
    with pytest.raises(PermissionError):
        resolve_source_file(
            "sources/大州系統_功能無法點選.md",
            params["expires"][0],
            params["signature"][0],
            settings,
            now=1_000,
            subject="attacker",
            membership_store=store,
        )


def test_portal_release_doc_path_is_used_for_hashed_sources(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    release_id = "release-e03700b32ec4"
    release_sources = settings.source_dir / "releases" / release_id / "sources"
    release_sources.mkdir(parents=True)
    (release_sources / "doc--cfe75ca0f2.md").write_text("# portal doc\n", encoding="utf-8")
    index_dir = settings.source_dir / "releases" / release_id / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "chunks.json").write_text(
        '{"chunks":[{"source_path":"sources/doc--cfe75ca0f2.md","title":"大州","allowed_groups":["it-helpdesk"]}]}',
        encoding="utf-8",
    )
    (settings.source_dir / "releases" / "active_release.json").write_text(
        '{"releaseId":"release-e03700b32ec4"}',
        encoding="utf-8",
    )

    response = AgentResponse(
        answer="ok",
        traceId="t",
        citations=[
            Citation(
                title="大州系統_功能無法點選",
                sourcePath="sources/doc--cfe75ca0f2.md",
                releaseId=release_id,
                sourceRefId="src-1",
            )
        ],
    )
    enriched = enrich_citation_urls(
        response, settings, now=1_000, viewer=_viewer(), membership_store=store
    )
    assert "/rag-sources/releases/release-e03700b32ec4/sources/doc--cfe75ca0f2.md" in (
        enriched.citations[0].url or ""
    )

    url = enriched.citations[0].url or ""
    params = parse_qs(urlparse(url).query)
    path = unquote(url.split("/rag-sources/", 1)[1].split("?", 1)[0])
    resolved = resolve_source_file(
        path,
        params["expires"][0],
        params["signature"][0],
        settings,
        now=1_000,
        subject=params["subject"][0],
        source_ref_id=(params.get("sourceRefId") or [None])[0],
        tenant_id=(params.get("tenantId") or [None])[0],
        membership_store=store,
    )
    assert resolved.read_text(encoding="utf-8").startswith("# portal doc")


def test_acl_denied_when_live_groups_no_longer_match(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    release_id = "release-acl"
    release_root = settings.source_dir / "releases" / release_id
    (release_root / "sources").mkdir(parents=True)
    (release_root / "sources" / "doc--secret.md").write_text("# secret\n", encoding="utf-8")
    (release_root / "index").mkdir(parents=True)
    (release_root / "index" / "chunks.json").write_text(
        '{"chunks":[{"source_path":"sources/doc--secret.md","allowed_groups":["vip-only"]}]}',
        encoding="utf-8",
    )
    (settings.source_dir / "releases" / "active_release.json").write_text(
        f'{{"releaseId":"{release_id}"}}',
        encoding="utf-8",
    )
    viewer = CitationViewerContext(subject="user-1", groups=("it-helpdesk",))
    url = build_source_url(
        "sources/doc--secret.md",
        settings,
        now=1_000,
        release_id=release_id,
        viewer=viewer,
        source_ref_id="src-secret",
        membership_store=store,
    )
    assert url is not None
    params = parse_qs(urlparse(url).query)
    path = unquote(url.split("/rag-sources/", 1)[1].split("?", 1)[0])
    with pytest.raises(PermissionError, match="access denied"):
        resolve_source_file(
            path,
            params["expires"][0],
            params["signature"][0],
            settings,
            now=1_000,
            subject=params["subject"][0],
            groups="vip-only",  # forged URL claim must be ignored
            source_ref_id=(params.get("sourceRefId") or [None])[0],
            membership_store=store,
        )


def test_revoked_membership_blocks_open_even_with_valid_signature(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    url = build_source_url(
        "sources/大州系統_功能無法點選.md",
        settings,
        now=1_000,
        viewer=_viewer(),
        membership_store=store,
    )
    assert url is not None
    params = parse_qs(urlparse(url).query)
    store.revoke("user-1")
    with pytest.raises(PermissionError, match="access denied"):
        resolve_source_file(
            "sources/大州系統_功能無法點選.md",
            params["expires"][0],
            params["signature"][0],
            settings,
            now=1_000,
            subject=params["subject"][0],
            membership_store=store,
        )


def test_authenticated_subject_mismatch_is_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    url = build_source_url(
        "sources/大州系統_功能無法點選.md",
        settings,
        now=1_000,
        viewer=_viewer(),
        membership_store=store,
    )
    assert url is not None
    params = parse_qs(urlparse(url).query)
    with pytest.raises(PermissionError, match="does not match"):
        resolve_source_file(
            "sources/大州系統_功能無法點選.md",
            params["expires"][0],
            params["signature"][0],
            settings,
            now=1_000,
            subject=params["subject"][0],
            authenticated_subject="other-user",
            membership_store=store,
        )


def test_format_agent_response_uses_enriched_url() -> None:
    response = AgentResponse(
        answer="ok",
        traceId="t",
        citations=[Citation(title="Doc", url="https://example.com/doc")],
    )
    assert "[Doc](https://example.com/doc)" in format_agent_response(response)


def test_sign_source_access_binds_subject(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sig_a = sign_source_access(
        "sources/a.md",
        1000,
        settings.asset_signing_key or "",
        subject="alice",
        groups=("g1",),
    )
    sig_b = sign_source_access(
        "sources/a.md",
        1000,
        settings.asset_signing_key or "",
        subject="bob",
        groups=("g1",),
    )
    assert sig_a != sig_b
    # Groups must not affect the signature (ACL is re-resolved live).
    sig_c = sign_source_access(
        "sources/a.md",
        1000,
        settings.asset_signing_key or "",
        subject="alice",
        groups=("other",),
    )
    assert sig_a == sig_c
