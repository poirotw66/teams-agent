"""Tests for Adapter → Backoffice original-source delivery."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from teams_agent.cards import build_agent_activity
from teams_agent.contracts import AgentResponse, Citation
from teams_agent.settings import AgentSettings, SettingsError
from teams_agent.source_api import SourceApiResponse
from teams_agent.source_delegation import issue_source_delegation
from teams_agent.source_links import (
    CitationViewerContext,
    authorize_original_open,
    build_original_url,
    enrich_citation_urls,
)
from teams_agent.source_routes import create_source_router
from teams_agent.viewer_sessions import InMemoryViewerMembershipStore


def _viewer() -> CitationViewerContext:
    return CitationViewerContext(subject="user-1", groups=("it-helpdesk",), tenant_id="t1")


def test_rag_asset_signing_key_alone_does_not_enable_source_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Local .env always has RAG_ASSET_SIGNING_KEY; that must not crash Adapter."""

    source_dir = tmp_path / "data"
    source_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_MODE", "echo")
    monkeypatch.setenv("RAG_SOURCE_DIR", str(source_dir))
    monkeypatch.setenv("RAG_ASSET_SIGNING_KEY", "local-signing-key-16+")
    monkeypatch.delenv("SOURCE_API_BASE_URL", raising=False)
    monkeypatch.delenv("SOURCE_API_TOKEN", raising=False)
    monkeypatch.delenv("SOURCE_DELEGATION_SECRET", raising=False)
    monkeypatch.delenv("AI_OPS_SOURCE_DELEGATION_SECRET", raising=False)
    monkeypatch.delenv("AI_OPS_BACKOFFICE_TOKEN", raising=False)

    settings = AgentSettings.from_env()
    assert settings.source_api_base_url is None
    assert settings.source_api_token is None
    assert settings.source_delegation_secret is None
    assert settings.asset_signing_key == "local-signing-key-16+"


def test_source_api_reuses_rag_signing_key_when_base_url_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "data"
    source_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_MODE", "echo")
    monkeypatch.setenv("RAG_SOURCE_DIR", str(source_dir))
    monkeypatch.setenv("RAG_ASSET_SIGNING_KEY", "local-signing-key-16+")
    monkeypatch.setenv("SOURCE_API_BASE_URL", "http://127.0.0.1:8092")
    monkeypatch.setenv("SOURCE_API_TOKEN", "service-token")
    monkeypatch.delenv("SOURCE_DELEGATION_SECRET", raising=False)
    monkeypatch.delenv("AI_OPS_SOURCE_DELEGATION_SECRET", raising=False)

    settings = AgentSettings.from_env()
    assert settings.source_api_base_url == "http://127.0.0.1:8092"
    assert settings.source_delegation_secret == "local-signing-key-16+"


def _settings(tmp_path: Path, *, with_source_api: bool = True) -> AgentSettings:
    source_dir = tmp_path / "data"
    sources = source_dir / "sources"
    sources.mkdir(parents=True)
    (sources / "doc.md").write_text("# Doc\n", encoding="utf-8")
    kwargs: dict[str, object] = {
        "source_dir": source_dir,
        "public_base_url": "https://bot.example.com",
        "asset_signing_key": "test-signing-key-long-enough",
        "asset_url_ttl_seconds": 3600,
        "allow_unauthenticated_requests": True,
    }
    if with_source_api:
        kwargs.update(
            {
                "source_api_base_url": "https://backoffice.example.com",
                "source_api_token": "service-token",
                "source_delegation_secret": "delegation-secret",
            }
        )
    return AgentSettings(**kwargs)


def test_settings_require_complete_source_api_triplet(tmp_path: Path) -> None:
    source_dir = tmp_path / "data"
    source_dir.mkdir()
    settings = AgentSettings(
        source_dir=source_dir,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
        source_api_base_url="https://backoffice.example.com",
    )
    with pytest.raises(SettingsError, match="SOURCE_API_BASE_URL"):
        settings.validate()


def test_enrich_mints_original_url_when_source_api_ready(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    response = AgentResponse(
        answer="ok",
        traceId="t",
        citations=[
            Citation(
                title="VPN",
                sourcePath="sources/doc.md",
                sourceRefId="src-vpn-1",
            )
        ],
    )

    enriched = enrich_citation_urls(
        response, settings, now=1_000, viewer=_viewer(), membership_store=store
    )

    assert enriched.citations[0].url is not None
    assert enriched.citations[0].url.startswith("https://bot.example.com/rag-sources/")
    assert enriched.citations[0].originalUrl is not None
    assert enriched.citations[0].originalUrl.startswith(
        "https://bot.example.com/rag-originals/src-vpn-1?"
    )


def test_card_prefers_original_open_action(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    response = AgentResponse(
        answer="請參考來源。",
        traceId="t",
        citations=[
            Citation(
                title="大州系統",
                sourcePath="sources/doc.md",
                sourceRefId="src-dazhou",
            )
        ],
    )
    enriched = enrich_citation_urls(
        response, settings, now=1_000, viewer=_viewer(), membership_store=store
    )
    activity = build_agent_activity(
        enriched, settings, now=1_000, viewer=_viewer()
    )
    assert not isinstance(activity, str)
    card = activity.attachments[0].content
    assert isinstance(card, dict)
    titles = [str(action.get("title")) for action in card.get("actions", [])]
    assert any(title.startswith("開啟原始檔案：") for title in titles)
    assert any(title.startswith("查看引用段落：") for title in titles)


def test_authorize_original_open_rejects_bad_signature(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    url = build_original_url(
        "src-1", settings, now=1_000, viewer=_viewer(), membership_store=store
    )
    assert url is not None
    query = parse_qs(urlparse(url).query)
    with pytest.raises(PermissionError, match="signature"):
        authorize_original_open(
            "src-1",
            query["expires"][0],
            "deadbeef",
            settings,
            now=1_000,
            subject="user-1",
            tenant_id="t1",
            authenticated_subject="user-1",
            membership_store=store,
        )


def test_rag_originals_route_proxies_backoffice_bytes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    from teams_agent.viewer_sessions import get_viewer_membership_store

    store = get_viewer_membership_store(settings)
    # Use wall-clock issuance so membership TTL aligns with authorize_original_open.
    url = build_original_url(
        "src-file-1",
        settings,
        viewer=_viewer(),
        membership_store=store,
    )
    assert url is not None
    path = urlparse(url).path
    query = urlparse(url).query

    app = FastAPI()
    app.include_router(create_source_router(settings))

    with patch(
        "teams_agent.source_routes.fetch_original_source_file",
        new=AsyncMock(
            return_value=SourceApiResponse(
                status=200,
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Disposition": 'inline; filename="guide.pdf"',
                    "X-Content-Type-Options": "nosniff",
                },
                body=b"%PDF-1.4 mock",
            )
        ),
    ) as mocked:
        client = TestClient(app)
        response = client.get(
            f"{path}?{query}",
            headers={
                "X-Viewer-Subject": "user-1",
                "X-Gateway-Secret": "test-signing-key-long-enough",
            },
        )

    assert response.status_code == 200, response.text
    assert response.content == b"%PDF-1.4 mock"
    assert response.headers["content-type"].startswith("application/pdf")
    mocked.assert_awaited_once()
    kwargs = mocked.await_args.kwargs
    assert kwargs["source_ref_id"] == "src-file-1"
    assert kwargs["subject"] == "user-1"
    assert kwargs["tenant_id"] == "t1"
    assert "it-helpdesk" in kwargs["groups"]


def test_issue_source_delegation_round_trips() -> None:
    from teams_agent.source_delegation import verify_source_delegation

    token = issue_source_delegation(
        subject="viewer@example.com",
        secret="shared-secret",
        tenant_id="tenant-a",
        groups=("grp_public",),
        now=1_700_000_000.0,
    )
    payload = verify_source_delegation(
        token, secret="shared-secret", now=1_700_000_010.0
    )
    assert payload["sub"] == "viewer@example.com"
    assert payload["tenantId"] == "tenant-a"
    assert payload["role"] == "VIEWER"
    assert payload["groups"] == ["grp_public"]
