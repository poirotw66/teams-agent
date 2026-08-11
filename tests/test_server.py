from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from teams_agent.media import build_asset_url
from teams_agent.server import (
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
