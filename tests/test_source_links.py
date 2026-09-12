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
        authenticated_subject=params["subject"][0],
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
            authenticated_subject="attacker",
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
        authenticated_subject=params["subject"][0],
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
            authenticated_subject=params["subject"][0],
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
            authenticated_subject=params["subject"][0],
            tenant_id=(params.get("tenantId") or [None])[0],
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


def test_unauthenticated_viewer_rejected_when_auth_required(tmp_path: Path) -> None:
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
    # Reject when authenticated_subject is missing
    with pytest.raises(PermissionError, match="Viewer authentication is required"):
        resolve_source_file(
            "sources/大州系統_功能無法點選.md",
            params["expires"][0],
            params["signature"][0],
            settings,
            now=1_000,
            subject=params["subject"][0],
            authenticated_subject=None,
            tenant_id=(params.get("tenantId") or [None])[0],
            membership_store=store,
        )


def test_tenant_mismatch_in_link_or_membership_is_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = InMemoryViewerMembershipStore()
    url = build_source_url(
        "sources/大州系統_功能無法點選.md",
        settings,
        now=1_000,
        viewer=_viewer(),  # tenant_id="t1"
        membership_store=store,
    )
    assert url is not None
    params = parse_qs(urlparse(url).query)

    # 1. Tampered tenantId in URL breaks HMAC signature
    with pytest.raises(PermissionError, match="Invalid source signature"):
        resolve_source_file(
            "sources/大州系統_功能無法點選.md",
            params["expires"][0],
            params["signature"][0],
            settings,
            now=1_000,
            subject=params["subject"][0],
            authenticated_subject=params["subject"][0],
            tenant_id="foreign-tenant",
            membership_store=store,
        )

    # 2. Re-signing with foreign tenant when membership is t1 is rejected in authorize_source_open
    foreign_sig = sign_source_access(
        "sources/大州系統_功能無法點選.md",
        int(params["expires"][0]),
        settings.asset_signing_key or "",
        subject=params["subject"][0],
        tenant_id="foreign-tenant",
    )
    with pytest.raises(PermissionError, match="Viewer tenant does not match citation tenant"):
        resolve_source_file(
            "sources/大州系統_功能無法點選.md",
            params["expires"][0],
            foreign_sig,
            settings,
            now=1_000,
            subject=params["subject"][0],
            authenticated_subject=params["subject"][0],
            tenant_id="foreign-tenant",
            membership_store=store,
        )


def test_viewer_hmac_token_minting_and_verification(tmp_path: Path) -> None:
    from teams_agent.source_links import create_viewer_token, verify_viewer_token

    settings = _settings(tmp_path)
    token = create_viewer_token("user-1", settings, tenant_id="tenant-1", expires_in=100, now=1000)
    assert token.startswith("v1.")
    verified = verify_viewer_token(token, settings, now=1050)
    assert verified is not None
    assert verified["sub"] == "user-1"
    assert verified["tid"] == "tenant-1"

    # Expired token
    assert verify_viewer_token(token, settings, now=1150) is None

    # Tampered token
    tampered = token[:-4] + "abcd"
    assert verify_viewer_token(tampered, settings, now=1050) is None


def test_file_backed_viewer_membership_store(tmp_path: Path) -> None:
    from teams_agent.viewer_sessions import FileBackedViewerMembershipStore

    store_file = tmp_path / "sessions" / "viewers.json"
    store1 = FileBackedViewerMembershipStore(store_file, default_ttl_seconds=100)
    store2 = FileBackedViewerMembershipStore(store_file, default_ttl_seconds=100)

    # Instance 1 remembers user-1
    entry = store1.remember(
        "user-1",
        groups=("it", "ops"),
        tenant_id="t1",
        revoked=False,
        ttl_seconds=50,
        now=1000,
    )
    assert entry.subject == "user-1"

    # Instance 2 resolves user-1 from persistent file
    resolved = store2.resolve("user-1", now=1020)
    assert resolved is not None
    assert resolved.subject == "user-1"
    assert resolved.groups == ("it", "ops")
    assert resolved.tenant_id == "t1"
    assert not resolved.revoked

    # Instance 1 revokes user-1
    store1.revoke("user-1")

    # Instance 2 sees revocation
    revoked = store2.resolve("user-1", now=1030)
    assert revoked is not None
    assert revoked.revoked is True
    assert revoked.groups == ()

    # Expired entry
    assert store2.resolve("user-1", now=1100) is None


def test_gcs_viewer_membership_store() -> None:
    from teams_agent.viewer_sessions import GcsViewerMembershipStore

    store1 = GcsViewerMembershipStore("test-bucket", allow_memory_fallback=True)
    store2 = GcsViewerMembershipStore("test-bucket", allow_memory_fallback=True)

    # Instance 1 remembers user across GCS shared store
    entry = store1.remember(
        "user-cloud-1",
        groups=("finance",),
        tenant_id="t-cloud",
        now=1000,
        ttl_seconds=60,
    )
    assert entry.subject == "user-cloud-1"

    # Instance 2 resolves user-cloud-1
    resolved = store2.resolve("user-cloud-1", now=1020)
    assert resolved is not None
    assert resolved.subject == "user-cloud-1"
    assert resolved.groups == ("finance",)
    assert resolved.tenant_id == "t-cloud"

    # Instance 1 revokes
    store1.revoke("user-cloud-1")
    revoked = store2.resolve("user-cloud-1", now=1030)
    assert revoked is not None
    assert revoked.revoked is True
    assert revoked.groups == ()


def test_authoritative_revocation_source_blocks_resolution() -> None:
    from teams_agent.viewer_sessions import (
        CallableRevocationResolver,
        InMemoryViewerMembershipStore,
    )

    revoked_principals = set()
    resolver = CallableRevocationResolver(lambda subj, tid: subj in revoked_principals)
    store = InMemoryViewerMembershipStore(revocation_resolver=resolver)

    store.remember("user-active", groups=("it",), now=1000, ttl_seconds=100)
    active = store.resolve("user-active", now=1020)
    assert active is not None
    assert not active.revoked
    assert active.groups == ("it",)

    # Principal is added to authoritative revocation source
    revoked_principals.add("user-active")
    authoritative_revoked = store.resolve("user-active", now=1030)
    assert authoritative_revoked is not None
    assert authoritative_revoked.revoked is True
    assert authoritative_revoked.groups == ()


