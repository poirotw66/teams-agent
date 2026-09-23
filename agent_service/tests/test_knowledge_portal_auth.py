from __future__ import annotations

from urllib.parse import quote

import pytest

from knowledge_portal.auth import (
    PortalAuthError,
    decode_portal_header_value,
    portal_header_auth_allowed,
    resolve_portal_actor,
)
from knowledge_portal.settings import PortalSettings


def _portal_settings(**overrides: object) -> PortalSettings:
    base = PortalSettings.from_env()
    return PortalSettings(**{**base.__dict__, **overrides})


def test_decode_portal_header_value_restores_unicode() -> None:
    encoded = quote("知識貢獻者")
    assert decode_portal_header_value(encoded) == "知識貢獻者"


def test_resolve_portal_actor_accepts_encoded_display_name() -> None:
    settings = _portal_settings(auth_mode="HEADER", deployment_environment="dev")
    actor = resolve_portal_actor(
        settings=settings,
        authorization=None,
        header_user_id="contributor.demo",
        header_user_name=quote("知識貢獻者"),
        header_role="CONTRIBUTOR",
        header_owner_units="IT Service Desk",
    )
    assert actor.display_name == "知識貢獻者"


def test_portal_header_auth_allowed_in_dev() -> None:
    settings = _portal_settings(deployment_environment="dev")
    assert portal_header_auth_allowed(settings) is True


def test_prod_rejects_browser_portal_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KNOWLEDGE_PORTAL_ALLOW_HEADER_AUTH", raising=False)
    settings = _portal_settings(
        auth_mode="HEADER",
        deployment_environment="prod",
        demo_mode=True,
        relaxed_workflow=True,
    )
    assert portal_header_auth_allowed(settings) is False
    assert settings.effective_relaxed_workflow() is False
    with pytest.raises(PortalAuthError, match="rejects X-Portal"):
        resolve_portal_actor(
            settings=settings,
            authorization=None,
            header_user_id="attacker",
            header_user_name="Attacker",
            header_role="PLATFORM",
            header_owner_units="IT Service Desk",
        )


def test_prod_break_glass_allows_header_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_PORTAL_ALLOW_HEADER_AUTH", "true")
    settings = _portal_settings(auth_mode="HEADER", deployment_environment="prod")
    assert portal_header_auth_allowed(settings) is True
    actor = resolve_portal_actor(
        settings=settings,
        authorization=None,
        header_user_id="lab.user",
        header_user_name="Lab User",
        header_role="CONTRIBUTOR",
        header_owner_units="IT Service Desk",
    )
    assert actor.user_id == "lab.user"
