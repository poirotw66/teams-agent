from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from teams_agent.media import build_asset_url
from teams_agent.server import (
    DualInboundTokenValidator,
    EntraPlaygroundTokenValidator,
    build_readiness,
    configure_inbound_auth,
    create_web_app,
)
from teams_agent.settings import AgentSettings


def make_settings(tmp_path: Path, **overrides) -> AgentSettings:
    defaults = {
        "asset_dir": tmp_path,
        "public_base_url": "https://bot.example.com",
        "asset_signing_key": "test-signing-key-long-enough",
        "client_id": "client-1",
        "client_secret": "secret-1",
        "tenant_id": "tenant-1",
    }
    defaults.update(overrides)
    return AgentSettings(**defaults)


def test_healthz_is_always_ok(tmp_path: Path) -> None:
    client = TestClient(create_web_app(make_settings(tmp_path)))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_ready_when_teams_credentials_are_present(tmp_path: Path) -> None:
    client = TestClient(create_web_app(make_settings(tmp_path)))

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["teamsAuth"] == "ready"


def test_readyz_is_not_ready_without_teams_credentials(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, client_id=None, client_secret=None, tenant_id=None)
    client = TestClient(create_web_app(settings))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["teamsAuth"] == "not_configured"


def test_readyz_accepts_the_local_unauthenticated_escape_hatch(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        client_id=None,
        client_secret=None,
        tenant_id=None,
        allow_unauthenticated_requests=True,
    )

    assert build_readiness(settings)["status"] == "ready"


def test_configure_inbound_auth_uses_entra_validator(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path, teams_inbound_auth_mode="entra")
    sentinel = object()
    calls = []

    class FakeServer:
        _token_validator = None

    class FakeApp:
        server = FakeServer()

    def fake_for_entra(client_id, tenant_id):
        calls.append((client_id, tenant_id))
        return sentinel

    monkeypatch.setattr(
        "teams_agent.server.TokenValidator.for_entra", fake_for_entra
    )

    app = FakeApp()
    configure_inbound_auth(app, settings)

    assert calls == [("client-1", "tenant-1")]
    assert isinstance(app.server._token_validator, EntraPlaygroundTokenValidator)
    assert app.server._token_validator._validator is sentinel


def test_configure_inbound_auth_dual_wraps_botframework_and_entra(
    tmp_path, monkeypatch
) -> None:
    settings = make_settings(tmp_path, teams_inbound_auth_mode="both")
    entra_sentinel = object()
    bot_framework = object()

    class FakeServer:
        _token_validator = bot_framework

    class FakeApp:
        server = FakeServer()

    monkeypatch.setattr(
        "teams_agent.server.TokenValidator.for_entra",
        lambda client_id, tenant_id: entra_sentinel,
    )

    app = FakeApp()
    configure_inbound_auth(app, settings)

    dual = app.server._token_validator
    assert isinstance(dual, DualInboundTokenValidator)
    assert dual._primary is bot_framework
    assert isinstance(dual._secondary, EntraPlaygroundTokenValidator)
    assert dual._secondary._validator is entra_sentinel


@pytest.mark.asyncio
async def test_entra_playground_validator_omits_botframework_service_url() -> None:
    calls = []

    class FakeValidator:
        async def validate_token(self, raw_token, service_url, scope):
            calls.append((raw_token, service_url, scope))
            return {"aud": "client-1"}

    validator = EntraPlaygroundTokenValidator(FakeValidator())

    payload = await validator.validate_token(
        "token",
        "https://playground.example/_connector",
        "scope-1",
    )

    assert payload == {"aud": "client-1"}
    assert calls == [("token", None, "scope-1")]


@pytest.mark.asyncio
async def test_dual_inbound_validator_falls_back_to_secondary() -> None:
    class RejectPrimary:
        async def validate_token(self, raw_token, service_url, scope):
            raise ValueError("botframework rejected")

    class AcceptSecondary:
        async def validate_token(self, raw_token, service_url, scope):
            return {"iss": "entra"}

    validator = DualInboundTokenValidator(RejectPrimary(), AcceptSecondary())

    payload = await validator.validate_token("token", "https://smba.example", None)

    assert payload == {"iss": "entra"}


@pytest.mark.asyncio
async def test_dual_inbound_validator_prefers_primary() -> None:
    class AcceptPrimary:
        async def validate_token(self, raw_token, service_url, scope):
            return {"iss": "botframework"}

    class RejectSecondary:
        async def validate_token(self, raw_token, service_url, scope):
            raise AssertionError("secondary should not run")

    validator = DualInboundTokenValidator(AcceptPrimary(), RejectSecondary())

    payload = await validator.validate_token("token", None, None)

    assert payload == {"iss": "botframework"}


def test_signed_asset_url_is_served(tmp_path: Path) -> None:
    Image.new("RGB", (64, 64), "white").save(tmp_path / "p01.png")
    settings = make_settings(tmp_path)
    client = TestClient(create_web_app(settings))
    url = urlparse(build_asset_url("p01.png", settings) or "")
    query = parse_qs(url.query)

    response = client.get(
        url.path,
        params={"expires": query["expires"][0], "signature": query["signature"][0]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_asset_with_a_bad_signature_is_forbidden(tmp_path: Path) -> None:
    Image.new("RGB", (64, 64), "white").save(tmp_path / "p01.png")
    settings = make_settings(tmp_path)
    client = TestClient(create_web_app(settings))
    url = urlparse(build_asset_url("p01.png", settings) or "")
    query = parse_qs(url.query)

    response = client.get(
        url.path, params={"expires": query["expires"][0], "signature": "tampered"}
    )

    assert response.status_code == 403


def test_asset_traversal_outside_the_asset_dir_is_forbidden(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = TestClient(create_web_app(settings))

    response = client.get(
        "/rag-assets/../../etc/passwd", params={"expires": "0", "signature": "x"}
    )

    assert response.status_code in {403, 404}


def test_missing_asset_returns_not_found(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = TestClient(create_web_app(settings))
    url = urlparse(build_asset_url("missing.png", settings) or "")
    query = parse_qs(url.query)

    response = client.get(
        url.path,
        params={"expires": query["expires"][0], "signature": query["signature"][0]},
    )

    assert response.status_code == 404


def test_signed_source_document_is_served(tmp_path: Path) -> None:
    from teams_agent.source_links import CitationViewerContext, build_source_url

    data_dir = tmp_path / "data"
    sources = data_dir / "sources"
    sources.mkdir(parents=True)
    (sources / "guide.md").write_text("# guide\n\n內容說明\n", encoding="utf-8")
    settings = make_settings(tmp_path, source_dir=data_dir)
    client = TestClient(create_web_app(settings))
    url = urlparse(
        build_source_url(
            "sources/guide.md",
            settings,
            viewer=CitationViewerContext(subject="user-1", groups=("it",)),
        )
        or ""
    )
    query = parse_qs(url.query)
    from teams_agent.source_links import create_viewer_token

    token = create_viewer_token("user-1", settings)
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 1. Opening without authentication is forbidden in production
    unauth_resp = client.get(
        url.path,
        params={
            "expires": query["expires"][0],
            "signature": query["signature"][0],
            "subject": query["subject"][0],
            "groups": query.get("groups", [""])[0],
        },
    )
    assert unauth_resp.status_code == 403

    # 2. Opening with authenticated Bearer token succeeds
    response = client.get(
        url.path,
        params={
            "expires": query["expires"][0],
            "signature": query["signature"][0],
            "subject": query["subject"][0],
            "groups": query.get("groups", [""])[0],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>guide</title>" in response.text
    assert "內容說明" in response.text

    raw = client.get(
        url.path,
        params={
            "expires": query["expires"][0],
            "signature": query["signature"][0],
            "subject": query["subject"][0],
            "groups": query.get("groups", [""])[0],
            "raw": "1",
        },
        headers=auth_headers,
    )
    assert raw.status_code == 200
    assert raw.text.startswith("# guide")

    # 3. Forged gateway header without gateway secret is rejected
    forged = client.get(
        url.path,
        params={
            "expires": query["expires"][0],
            "signature": query["signature"][0],
            "subject": query["subject"][0],
            "groups": query.get("groups", [""])[0],
        },
        headers={"X-Viewer-Subject": "user-1"},
    )
    assert forged.status_code == 403

    # 4. Verified gateway header with secret succeeds
    gateway_resp = client.get(
        url.path,
        params={
            "expires": query["expires"][0],
            "signature": query["signature"][0],
            "subject": query["subject"][0],
            "groups": query.get("groups", [""])[0],
        },
        headers={
            "X-Viewer-Subject": "user-1",
            "X-Gateway-Secret": settings.asset_signing_key or "",
        },
    )
    assert gateway_resp.status_code == 200

    denied = client.get(
        url.path,
        params={
            "expires": query["expires"][0],
            "signature": query["signature"][0],
            "subject": "other-user",
            "groups": query.get("groups", [""])[0],
        },
        headers=auth_headers,
    )
    assert denied.status_code == 403


def test_citation_url_decouples_token_and_blocks_forwarded_links(tmp_path: Path) -> None:
    from teams_agent.source_links import (
        CitationViewerContext,
        build_source_url,
        create_viewer_token,
    )

    data_dir = tmp_path / "data"
    sources = data_dir / "sources"
    sources.mkdir(parents=True)
    (sources / "manual.md").write_text("# manual\n\n員工使用手冊內容\n", encoding="utf-8")
    settings = make_settings(tmp_path, source_dir=data_dir)
    app = create_web_app(settings)
    alice_client = TestClient(app)

    # 1. Build citation URL for Alice: must NOT contain token parameter
    full_url = build_source_url(
        "sources/manual.md",
        settings,
        viewer=CitationViewerContext(subject="user-alice", groups=("all",)),
    )
    assert full_url is not None
    assert "token=" not in full_url
    assert "subject=user-alice" in full_url

    parsed = urlparse(full_url)
    query = parse_qs(parsed.query)
    citation_params = {k: v[0] for k, v in query.items()}

    # 2. Unauthenticated request without session redirects to login page
    unauth_resp = alice_client.get(
        parsed.path,
        params=citation_params,
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert unauth_resp.status_code == 302
    assert "/sources/login" in unauth_resp.headers["location"]

    # 3. Alice authenticates via /sources/login, receiving teams_viewer_token session cookie
    alice_token = create_viewer_token("user-alice", settings)
    login_resp = alice_client.post(
        "/sources/login",
        data={"token": alice_token, "redirect_url": parsed.path},
        follow_redirects=False,
    )
    assert login_resp.status_code == 302
    assert "teams_viewer_token" in login_resp.cookies

    # 4. Authenticated Alice opens the citation link: 200 OK
    alice_resp = alice_client.get(parsed.path, params=citation_params)
    assert alice_resp.status_code == 200
    assert "員工使用手冊內容" in alice_resp.text

    # 5. Forwarded link protection: Bob opens Alice's citation link with Bob's active session
    bob_client = TestClient(app)
    bob_token = create_viewer_token("user-bob", settings)
    bob_client.cookies.set("teams_viewer_token", bob_token)

    bob_resp = bob_client.get(parsed.path, params=citation_params)
    assert bob_resp.status_code == 403
    assert "Viewer identity does not match the signed citation subject" in bob_resp.text


def test_unauthenticated_browser_redirects_to_login_and_submits(tmp_path: Path) -> None:
    from teams_agent.source_links import (
        CitationViewerContext,
        build_source_url,
        create_viewer_token,
    )

    data_dir = tmp_path / "data"
    sources = data_dir / "sources"
    sources.mkdir(parents=True)
    (sources / "faq.md").write_text("# faq\n\n問答說明\n", encoding="utf-8")
    settings = make_settings(tmp_path, source_dir=data_dir)
    client = TestClient(create_web_app(settings))

    full_url = build_source_url(
        "sources/faq.md",
        settings,
        viewer=CitationViewerContext(subject="user-login-1", groups=("all",)),
    )
    assert full_url is not None
    parsed = urlparse(full_url)
    query = parse_qs(parsed.query)

    # 1. Unauthenticated browser request (Accept: text/html) redirects to /sources/login
    unauth_resp = client.get(
        parsed.path,
        params={
            "expires": query["expires"][0],
            "signature": query["signature"][0],
            "subject": query["subject"][0],
        },
        headers={"Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )
    assert unauth_resp.status_code == 302
    assert "/sources/login?redirect_url=" in unauth_resp.headers["location"]

    # 2. GET /sources/login renders Traditional Chinese verification page
    login_page = client.get("/sources/login")
    assert login_page.status_code == 200
    assert "知識庫來源文件存取驗證" in login_page.text

    # 3. Submitting valid token to /sources/login establishes session cookie
    valid_token = create_viewer_token("user-login-1", settings)
    login_post = client.post(
        "/sources/login",
        data={"token": valid_token, "redirect_url": parsed.path},
        follow_redirects=False,
    )
    assert login_post.status_code == 302
    assert "teams_viewer_token" in login_post.cookies


def test_sources_sso_login_and_callback_flow(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    sources = data_dir / "sources"
    sources.mkdir(parents=True)
    (sources / "corp_guide.md").write_text("# Guide\n\n企業內網指南內容\n", encoding="utf-8")

    settings = make_settings(
        tmp_path,
        source_dir=data_dir,
        client_id="entra-client-123",
        client_secret="entra-secret-xyz",
        tenant_id="entra-tenant-789",
    )
    app = create_web_app(settings)

    # Mock OAuth token exchanger on app.state
    async def mock_exchanger(code: str, redirect_uri: str) -> dict[str, Any]:
        assert code == "mock-auth-code-1"
        assert "/sources/auth/callback" in redirect_uri
        return {
            "sub": "user-sso-alice",
            "email": "alice@company.com",
            "tenant_id": "entra-tenant-789",
            "groups": ["all", "finance"],
        }

    app.state.oauth_token_exchanger = mock_exchanger
    client = TestClient(app)

    # 1. Login page does NOT contain obsolete claim about one-time citation credentials
    login_page = client.get("/sources/login?redirect_url=/rag-sources/sources/corp_guide.md")
    assert login_page.status_code == 200
    assert "系統會自動在參考來源連結中附帶一次性安全檢視憑證" not in login_page.text
    assert "使用 Microsoft 365 / 公司帳號登入 (SSO)" in login_page.text

    # 2. GET /sources/auth/login redirects to Entra ID OAuth authorize endpoint
    auth_login = client.get(
        "/sources/auth/login?redirect_url=/rag-sources/sources/corp_guide.md",
        follow_redirects=False,
    )
    assert auth_login.status_code == 302
    auth_loc = auth_login.headers["location"]
    assert "login.microsoftonline.com/entra-tenant-789/oauth2/v2.0/authorize" in auth_loc
    assert "client_id=entra-client-123" in auth_loc
    assert "state=" in auth_loc

    # Extract state param from redirect location
    parsed_auth = urlparse(auth_loc)
    auth_params = parse_qs(parsed_auth.query)
    state = auth_params["state"][0]

    # 3. GET /sources/auth/callback completes login, sets session cookie, and redirects to target
    callback_resp = client.get(
        "/sources/auth/callback",
        params={"code": "mock-auth-code-1", "state": state},
        follow_redirects=False,
    )
    assert callback_resp.status_code == 302
    assert callback_resp.headers["location"] == "/rag-sources/sources/corp_guide.md"
    assert "teams_viewer_token" in callback_resp.cookies

    # 4. Already authenticated browser revisiting /sources/login auto-redirects
    auto_redirect = client.get(
        "/sources/login?redirect_url=/rag-sources/sources/corp_guide.md",
        follow_redirects=False,
    )
    assert auto_redirect.status_code == 302
    assert auto_redirect.headers["location"] == "/rag-sources/sources/corp_guide.md"



