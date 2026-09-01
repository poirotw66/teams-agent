from __future__ import annotations

from urllib.parse import quote

from knowledge_portal.auth import decode_portal_header_value, resolve_portal_actor
from knowledge_portal.settings import PortalSettings


def test_decode_portal_header_value_restores_unicode() -> None:
    encoded = quote("知識貢獻者")
    assert decode_portal_header_value(encoded) == "知識貢獻者"


def test_resolve_portal_actor_accepts_encoded_display_name() -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "auth_mode", "HEADER")
    actor = resolve_portal_actor(
        settings=settings,
        authorization=None,
        header_user_id="contributor.demo",
        header_user_name=quote("知識貢獻者"),
        header_role="CONTRIBUTOR",
        header_owner_units="IT Service Desk",
    )
    assert actor.display_name == "知識貢獻者"
