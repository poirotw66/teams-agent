"""Tests for signed knowledge-source citation links."""

from pathlib import Path

from teams_agent.cards import build_agent_activity
from teams_agent.contracts import AgentResponse, Citation, format_agent_response
from teams_agent.settings import AgentSettings
from teams_agent.source_links import (
    build_source_url,
    enrich_citation_urls,
    resolve_source_file,
)


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


def test_enrich_citation_urls_fills_missing_url_from_source_path(tmp_path: Path) -> None:
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

    enriched = enrich_citation_urls(response, settings, now=1_000)

    assert enriched.citations[0].url is not None
    assert enriched.citations[0].url.startswith(
        "https://bot.example.com/rag-sources/sources/"
    )
    assert "signature=" in enriched.citations[0].url


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

    enriched = enrich_citation_urls(response, settings, now=1_000)

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

    activity = build_agent_activity(response, settings, now=1_000)
    assert isinstance(activity, str)
    assert "[大州系統_功能無法點選](https://bot.example.com/rag-sources/" in activity


def test_resolve_source_file_serves_markdown(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    url = build_source_url(
        "sources/大州系統_功能無法點選.md", settings, now=1_000
    )
    assert url is not None
    query = url.split("?", 1)[1]
    params = dict(part.split("=", 1) for part in query.split("&"))
    resolved = resolve_source_file(
        "sources/大州系統_功能無法點選.md",
        params["expires"],
        params["signature"],
        settings,
        now=1_000,
    )
    assert resolved.read_text(encoding="utf-8").startswith("# 大州")


def test_portal_release_doc_path_is_used_for_hashed_sources(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    release_id = "release-e03700b32ec4"
    release_sources = settings.source_dir / "releases" / release_id / "sources"
    release_sources.mkdir(parents=True)
    (release_sources / "doc--cfe75ca0f2.md").write_text("# portal doc\n", encoding="utf-8")
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
            )
        ],
    )
    enriched = enrich_citation_urls(response, settings, now=1_000)
    assert "/rag-sources/releases/release-e03700b32ec4/sources/doc--cfe75ca0f2.md" in (
        enriched.citations[0].url or ""
    )

    url = enriched.citations[0].url or ""
    query = url.split("?", 1)[1]
    params = dict(part.split("=", 1) for part in query.split("&"))
    path = url.split("/rag-sources/", 1)[1].split("?", 1)[0]
    from urllib.parse import unquote

    resolved = resolve_source_file(
        unquote(path),
        params["expires"],
        params["signature"],
        settings,
        now=1_000,
    )
    assert resolved.read_text(encoding="utf-8").startswith("# portal doc")


def test_legacy_sources_doc_url_falls_back_to_active_release(tmp_path: Path) -> None:
    """Already-issued links signed as sources/doc--*.md still open from release."""

    from teams_agent.source_links import sign_source_path

    settings = _settings(tmp_path)
    release_id = "release-e03700b32ec4"
    release_sources = settings.source_dir / "releases" / release_id / "sources"
    release_sources.mkdir(parents=True)
    (release_sources / "doc--cfe75ca0f2.md").write_text("# legacy open\n", encoding="utf-8")
    (settings.source_dir / "releases" / "active_release.json").write_text(
        '{"releaseId":"release-e03700b32ec4"}',
        encoding="utf-8",
    )
    expires = 1_000 + settings.asset_url_ttl_seconds
    legacy_path = "sources/doc--cfe75ca0f2.md"
    signature = sign_source_path(
        legacy_path, expires, settings.asset_signing_key or ""
    )

    resolved = resolve_source_file(
        legacy_path,
        str(expires),
        signature,
        settings,
        now=1_000,
    )
    assert resolved.read_text(encoding="utf-8").startswith("# legacy open")


def test_format_agent_response_uses_enriched_url() -> None:
    response = AgentResponse(
        answer="ok",
        traceId="t",
        citations=[Citation(title="Doc", url="https://example.com/doc")],
    )
    assert "[Doc](https://example.com/doc)" in format_agent_response(response)
