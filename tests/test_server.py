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


def test_sources_sso_security_validations_and_subject_alignment(tmp_path: Path) -> None:
    from urllib.parse import quote

    from teams_agent.source_links import verify_viewer_token
    from teams_agent.viewer_sessions import get_viewer_membership_store

    data_dir = tmp_path / "data"
    sources = data_dir / "sources"
    sources.mkdir(parents=True)
    (sources / "doc.md").write_text("# Doc\n", encoding="utf-8")

    settings = make_settings(
        tmp_path,
        source_dir=data_dir,
        client_id="client-sec-1",
        client_secret="sec-xyz",
        tenant_id="tenant-sec-1",
    )
    app = create_web_app(settings)

    # Pre-register existing membership with groups ("sec_audit", "it_ops") for Entra object ID
    entra_oid = "00001111-2222-3333-4444-555566667777"
    store = get_viewer_membership_store(settings)
    store.remember(entra_oid, groups=["sec_audit", "it_ops"], tenant_id="tenant-sec-1")

    # Exchanger returns Entra OID and email, with EMPTY groups
    async def mock_token_exchanger(code: str, redirect_uri: str) -> dict[str, Any]:
        return {
            "oid": entra_oid,
            "sub": "some-sub-id",
            "preferred_username": "bob@company.com",
            "email": "bob@company.com",
            "tenant_id": "tenant-sec-1",
            "groups": [],  # Empty groups from token
        }

    app.state.oauth_token_exchanger = mock_token_exchanger
    client = TestClient(app)

    # 1. Test safe redirect check against open redirect attack
    malicious_redirect = "//evil.com/phishing"
    login_resp = client.get(f"/sources/auth/login?redirect_url={quote(malicious_redirect)}", follow_redirects=False)
    assert login_resp.status_code == 302
    session_cookie = login_resp.cookies.get("sso_auth_session")
    assert session_cookie is not None
    parsed_auth = urlparse(login_resp.headers["location"])
    auth_params = parse_qs(parsed_auth.query)
    state = auth_params["state"][0]

    # Callback with malicious redirect falls back to /healthz, NEVER evil.com
    cb_resp = client.get(f"/sources/auth/callback?code=mock-code&state={state}", follow_redirects=False)
    assert cb_resp.status_code == 302
    assert cb_resp.headers["location"] == "/healthz"

    # 2. Subject alignment & groups preservation:
    # Token subject MUST be entra_oid (not bob@company.com)
    viewer_token = cb_resp.cookies["teams_viewer_token"]
    payload = verify_viewer_token(viewer_token, settings)
    assert payload is not None
    assert payload["sub"] == entra_oid

    # Existing membership groups ("sec_audit", "it_ops") must NOT have been wiped out by empty groups in token
    current_membership = store.resolve(entra_oid)
    assert current_membership is not None
    assert "sec_audit" in current_membership.groups
    assert "it_ops" in current_membership.groups

    # 3. One-time state consumption check:
    # Replaying with the session cookie MUST be rejected with "already been consumed"
    client.cookies.set("sso_auth_session", session_cookie)
    replay_resp = client.get(f"/sources/auth/callback?code=mock-code&state={state}", follow_redirects=False)
    assert replay_resp.status_code == 403
    assert "already been consumed" in replay_resp.text

    # Replaying without session cookie MUST be rejected with "Missing or invalid SSO session cookie"
    client.cookies.delete("sso_auth_session")
    no_cookie_resp = client.get(f"/sources/auth/callback?code=mock-code&state={state}", follow_redirects=False)
    assert no_cookie_resp.status_code == 403
    assert "Missing or invalid SSO session cookie" in no_cookie_resp.text

    # 4. CSRF / session cookie binding check: callback without session cookie MUST be rejected with 403
    client_victim = TestClient(app)
    login_resp2 = client_victim.get("/sources/auth/login?redirect_url=/sources/doc.md", follow_redirects=False)
    assert login_resp2.status_code == 302
    state2 = parse_qs(urlparse(login_resp2.headers["location"]).query)["state"][0]

    # Attacker without victim's session cookie tries to consume victim's state
    client_attacker = TestClient(app)
    stolen_state_resp = client_attacker.get(f"/sources/auth/callback?code=mock-code&state={state2}")
    assert stolen_state_resp.status_code == 403
    assert "Missing or invalid SSO session cookie" in stolen_state_resp.text


def test_sources_login_endpoints_reject_open_redirect(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    sources = data_dir / "sources"
    sources.mkdir(parents=True)
    (sources / "doc.md").write_text("# Doc\n", encoding="utf-8")

    settings = make_settings(
        tmp_path,
        source_dir=sources,
        asset_signing_key="test-key-safe-redirect-32-bytes-long!",
        public_base_url="https://agent.example.com",
    )
    app = create_web_app(settings)
    client = TestClient(app)

    from teams_agent.source_links import create_viewer_token

    token = create_viewer_token("user-test", settings)

    # 1. GET /sources/login with protocol-relative URL
    resp_get_proto = client.get(f"/sources/login?token={token}&redirect_url=//attacker.com/malicious", follow_redirects=False)
    assert resp_get_proto.status_code == 302
    assert resp_get_proto.headers["location"] == "/healthz"

    # 2. GET /sources/login with backslash escape
    resp_get_bs = client.get(f"/sources/login?token={token}&redirect_url=/\\attacker.com", follow_redirects=False)
    assert resp_get_bs.status_code == 302
    assert resp_get_bs.headers["location"] == "/healthz"

    # 3. GET /sources/login with safe relative path
    resp_get_safe = client.get(f"/sources/login?token={token}&redirect_url=/sources/doc.md", follow_redirects=False)
    assert resp_get_safe.status_code == 302
    assert resp_get_safe.headers["location"] == "/sources/doc.md"

    # 4. POST /sources/login with open redirect attempt
    resp_post_evil = client.post(
        "/sources/login",
        data={"token": token, "redirect_url": "//evil.com"},
        follow_redirects=False,
    )
    assert resp_post_evil.status_code == 302
    assert resp_post_evil.headers["location"] == "/healthz"

    # 5. POST /sources/login with safe relative path
    resp_post_safe = client.post(
        "/sources/login",
        data={"token": token, "redirect_url": "/sources/doc.md"},
        follow_redirects=False,
    )
    assert resp_post_safe.status_code == 302
    assert resp_post_safe.headers["location"] == "/sources/doc.md"


def test_real_oidc_id_token_cryptographic_verification(tmp_path: Path) -> None:
    import time
    from urllib.parse import parse_qs, urlparse

    import jwt
    from fastapi import HTTPException

    from teams_agent.server import verify_entra_id_token

    tenant_id = "test-entra-tenant-uuid"
    client_id = "test-entra-client-uuid"
    secret_key = "test-hmac-secret-for-oidc-32-bytes-long!"
    now_ts = int(time.time())

    # 1. Direct unit verification of verify_entra_id_token
    valid_payload = {
        "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        "aud": client_id,
        "sub": "entra-sub-001",
        "oid": "entra-oid-001",
        "preferred_username": "testuser@company.com",
        "email": "testuser@company.com",
        "nonce": "test-nonce-12345",
        "exp": now_ts + 3600,
        "iat": now_ts,
    }
    valid_token = jwt.encode(valid_payload, secret_key, algorithm="HS256")

    # Happy path: valid signature, iss, aud, exp, nonce
    claims = verify_entra_id_token(
        valid_token,
        client_id=client_id,
        tenant_id=tenant_id,
        expected_nonce="test-nonce-12345",
        signing_key=secret_key,
        allowed_algorithms=["HS256"],
    )
    assert claims["oid"] == "entra-oid-001"
    assert claims["sub"] == "entra-sub-001"

    # Bad signature
    with pytest.raises(HTTPException) as exc:
        verify_entra_id_token(
            valid_token,
            client_id=client_id,
            tenant_id=tenant_id,
            expected_nonce="test-nonce-12345",
            signing_key="wrong-secret-key",
            allowed_algorithms=["HS256"],
        )
    assert exc.value.status_code == 401
    assert "signature verification failed" in exc.value.detail

    # Bad issuer (iss)
    bad_iss_token = jwt.encode({**valid_payload, "iss": "https://evil.com/v2.0"}, secret_key, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        verify_entra_id_token(
            bad_iss_token,
            client_id=client_id,
            tenant_id=tenant_id,
            expected_nonce="test-nonce-12345",
            signing_key=secret_key,
            allowed_algorithms=["HS256"],
        )
    assert exc.value.status_code == 401
    assert "issuer mismatch" in exc.value.detail

    # Bad audience (aud)
    bad_aud_token = jwt.encode({**valid_payload, "aud": "wrong-client-id"}, secret_key, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        verify_entra_id_token(
            bad_aud_token,
            client_id=client_id,
            tenant_id=tenant_id,
            expected_nonce="test-nonce-12345",
            signing_key=secret_key,
            allowed_algorithms=["HS256"],
        )
    assert exc.value.status_code == 401
    assert "audience mismatch" in exc.value.detail

    # Expired token (exp)
    expired_token = jwt.encode({**valid_payload, "exp": now_ts - 100}, secret_key, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        verify_entra_id_token(
            expired_token,
            client_id=client_id,
            tenant_id=tenant_id,
            expected_nonce="test-nonce-12345",
            signing_key=secret_key,
            allowed_algorithms=["HS256"],
        )
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail

    # Nonce mismatch (nonce)
    with pytest.raises(HTTPException) as exc:
        verify_entra_id_token(
            valid_token,
            client_id=client_id,
            tenant_id=tenant_id,
            expected_nonce="different-nonce-99999",
            signing_key=secret_key,
            allowed_algorithms=["HS256"],
        )
    assert exc.value.status_code == 401
    assert "nonce mismatch" in exc.value.detail

    # Missing required claim (missing nonce)
    missing_nonce_payload = {k: v for k, v in valid_payload.items() if k != "nonce"}
    missing_nonce_token = jwt.encode(missing_nonce_payload, secret_key, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        verify_entra_id_token(
            missing_nonce_token,
            client_id=client_id,
            tenant_id=tenant_id,
            expected_nonce="test-nonce-12345",
            signing_key=secret_key,
            allowed_algorithms=["HS256"],
        )
    assert exc.value.status_code == 401
    assert "missing required claim" in exc.value.detail

    # 2. End-to-end integration test through viewer_auth_callback with real signed token
    sources = tmp_path / "sources"
    sources.mkdir(parents=True)
    (sources / "doc.md").write_text("# Doc\n", encoding="utf-8")

    settings = make_settings(
        tmp_path,
        source_dir=sources,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret="test-client-secret",
        asset_signing_key="test-key-oidc-flow-32-bytes-long!",
        public_base_url="https://agent.example.com",
    )
    app = create_web_app(settings)
    app.state.id_token_key = secret_key
    app.state.id_token_algorithms = ["HS256"]

    client = TestClient(app)

    # Step A: Initiate SSO login
    login_resp = client.get("/sources/auth/login?redirect_url=/sources/doc.md", follow_redirects=False)
    assert login_resp.status_code == 302
    session_cookie = login_resp.cookies["sso_auth_session"]
    parsed_auth = urlparse(login_resp.headers["location"])
    auth_params = parse_qs(parsed_auth.query)
    state = auth_params["state"][0]
    expected_nonce = auth_params["nonce"][0]

    # Step B: Generate real signed ID token containing the expected nonce from Step A
    id_token_for_callback = jwt.encode(
        {**valid_payload, "nonce": expected_nonce, "oid": "entra-oid-live-999"},
        secret_key,
        algorithm="HS256",
    )

    # Mock token exchanger returning the real signed id_token string
    async def token_exchanger_with_real_token(_code: str, _cb: str) -> dict:
        return {"id_token": id_token_for_callback}

    app.state.oauth_token_exchanger = token_exchanger_with_real_token

    # Step C: Execute callback with valid signed token
    client.cookies.set("sso_auth_session", session_cookie)
    cb_resp = client.get(f"/sources/auth/callback?code=real-test-code&state={state}", follow_redirects=False)
    assert cb_resp.status_code == 302
    assert cb_resp.headers["location"] == "/sources/doc.md"

    from teams_agent.source_links import verify_viewer_token

    viewer_token = cb_resp.cookies["teams_viewer_token"]
    verified = verify_viewer_token(viewer_token, settings)
    assert verified is not None
    assert verified["sub"] == "entra-oid-live-999"  # OID was extracted and verified!


def test_oidc_strict_tenant_isolation(tmp_path: Path) -> None:
    """Verify that configured tenant A strictly rejects tokens signed for tenant B."""
    import time
    from urllib.parse import parse_qs, urlparse

    import jwt
    import pytest
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from teams_agent.server import create_web_app, verify_entra_id_token

    tenant_a = "tenant-uuid-alpha"
    tenant_b = "tenant-uuid-bravo"
    client_id = "client-app-uuid"
    secret_key = "test-secret-key-for-tenant-isolation-test!"
    now_ts = int(time.time())

    token_for_b = jwt.encode(
        {
            "iss": f"https://login.microsoftonline.com/{tenant_b}/v2.0",
            "tid": tenant_b,
            "aud": client_id,
            "sub": "user-from-tenant-b",
            "oid": "oid-from-tenant-b",
            "nonce": "test-nonce-abc",
            "exp": now_ts + 3600,
            "iat": now_ts,
        },
        secret_key,
        algorithm="HS256",
    )

    # Unit check: direct verification with tenant_a config MUST reject token_for_b
    with pytest.raises(HTTPException) as exc:
        verify_entra_id_token(
            token_for_b,
            client_id=client_id,
            tenant_id=tenant_a,
            expected_nonce="test-nonce-abc",
            signing_key=secret_key,
            allowed_algorithms=["HS256"],
        )
    assert exc.value.status_code == 401
    assert "issuer mismatch" in exc.value.detail or "tenant mismatch" in exc.value.detail

    # Unit check: token with forged iss but tid=tenant_b MUST also be rejected
    forged_token = jwt.encode(
        {
            "iss": f"https://login.microsoftonline.com/{tenant_a}/v2.0",
            "tid": tenant_b,
            "aud": client_id,
            "sub": "user-from-tenant-b",
            "oid": "oid-from-tenant-b",
            "nonce": "test-nonce-abc",
            "exp": now_ts + 3600,
            "iat": now_ts,
        },
        secret_key,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        verify_entra_id_token(
            forged_token,
            client_id=client_id,
            tenant_id=tenant_a,
            expected_nonce="test-nonce-abc",
            signing_key=secret_key,
            allowed_algorithms=["HS256"],
        )
    assert exc.value.status_code == 401
    assert "tenant mismatch" in exc.value.detail

    # Unit check: multi-tenant allowlist allows tenant_b but rejects tenant_c
    claims_b = verify_entra_id_token(
        token_for_b,
        client_id=client_id,
        tenant_id="common",
        allowed_tenants=[tenant_a, tenant_b],
        expected_nonce="test-nonce-abc",
        signing_key=secret_key,
        allowed_algorithms=["HS256"],
    )
    assert claims_b["tid"] == tenant_b

    token_for_c = jwt.encode(
        {
            "iss": "https://login.microsoftonline.com/tenant-uuid-charlie/v2.0",
            "tid": "tenant-uuid-charlie",
            "aud": client_id,
            "sub": "user-c",
            "nonce": "test-nonce-abc",
            "exp": now_ts + 3600,
            "iat": now_ts,
        },
        secret_key,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        verify_entra_id_token(
            token_for_c,
            client_id=client_id,
            tenant_id="common",
            allowed_tenants=[tenant_a, tenant_b],
            expected_nonce="test-nonce-abc",
            signing_key=secret_key,
            allowed_algorithms=["HS256"],
        )
    assert exc.value.status_code == 401

    # Integration check: SSO callback endpoint rejects foreign tenant token
    sources = tmp_path / "sources"
    sources.mkdir(parents=True)
    (sources / "doc.md").write_text("# Doc\n", encoding="utf-8")

    settings = make_settings(
        tmp_path,
        source_dir=sources,
        tenant_id=tenant_a,
        client_id=client_id,
        client_secret="sec",
        asset_signing_key="key",
        public_base_url="https://agent.example.com",
    )

    app = create_web_app(settings)
    app.state.id_token_key = secret_key
    app.state.id_token_algorithms = ["HS256"]
    client = TestClient(app)

    login_resp = client.get("/sources/auth/login?redirect_url=/sources/doc.md", follow_redirects=False)
    session_cookie = login_resp.cookies["sso_auth_session"]
    parsed_auth = urlparse(login_resp.headers["location"])
    auth_params = parse_qs(parsed_auth.query)
    state = auth_params["state"][0]
    expected_nonce = auth_params["nonce"][0]

    token_b_with_nonce = jwt.encode(
        {
            "iss": f"https://login.microsoftonline.com/{tenant_b}/v2.0",
            "tid": tenant_b,
            "aud": client_id,
            "sub": "foreign-user",
            "oid": "foreign-oid",
            "nonce": expected_nonce,
            "exp": now_ts + 3600,
            "iat": now_ts,
        },
        secret_key,
        algorithm="HS256",
    )

    async def foreign_token_exchanger(_c: str, _cb: str) -> dict:
        return {"id_token": token_b_with_nonce}

    app.state.oauth_token_exchanger = foreign_token_exchanger
    client.cookies.set("sso_auth_session", session_cookie)
    cb_resp = client.get(f"/sources/auth/callback?code=code&state={state}", follow_redirects=False)
    assert cb_resp.status_code == 401
    assert "teams_viewer_token" not in cb_resp.cookies
