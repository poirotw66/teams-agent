import os

os.environ.setdefault("DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS", "true")

from microsoft_teams.api import MessageActivity

from teams_agent.agent import resolve_request_groups
from teams_agent.contracts import AgentRequest, activity_tenant_id
from teams_agent.source_links import citation_source_groups, citation_source_tenant_id
from teams_agent.text import clean_message_text

_AGENTS_PLAYGROUND_TENANT_ID = "00000000-0000-0000-0000-0000000000001"


def make_message_activity(**overrides) -> MessageActivity:
    payload: dict = {
        "type": "message",
        "id": "activity-1",
        "channelId": "msteams",
        "from": {"id": "teams-user-1"},
        "conversation": {"id": "conversation-1"},
        "recipient": {"id": "bot-1"},
    }
    payload.update(overrides)
    return MessageActivity.model_validate(payload)


def test_clean_message_text_normalizes_whitespace() -> None:
    assert clean_message_text("  hello \n Teams  ") == "hello Teams"


def test_clean_message_text_handles_none() -> None:
    assert clean_message_text(None) == ""


def test_playground_citations_use_shared_knowledge_tenant() -> None:
    assert (
        citation_source_tenant_id(
            "playground",
            _AGENTS_PLAYGROUND_TENANT_ID,
        )
        == "default"
    )
    assert citation_source_groups(
        "playground",
        _AGENTS_PLAYGROUND_TENANT_ID,
        (),
    ) == ("grp_public",)


def test_teams_citations_preserve_tenant() -> None:
    assert citation_source_tenant_id("msteams", "enterprise-tenant") == "enterprise-tenant"


def test_playground_request_injects_grp_public_for_synthetic_tenant() -> None:
    activity = make_message_activity(
        channelId="playground",
        channelData={"tenant": {"id": _AGENTS_PLAYGROUND_TENANT_ID}},
    )
    groups = resolve_request_groups(activity)
    request = AgentRequest.from_activity(activity, "VPN 密碼被鎖怎麼辦？", groups=groups)

    assert activity_tenant_id(activity) == _AGENTS_PLAYGROUND_TENANT_ID
    assert groups == ["grp_public"]
    assert request.user.groups == ["grp_public"]


def test_msteams_request_keeps_empty_groups() -> None:
    activity = make_message_activity(
        channelId="msteams",
        channelData={"tenant": {"id": "enterprise-tenant"}},
    )
    groups = resolve_request_groups(activity)
    request = AgentRequest.from_activity(activity, "VPN 密碼被鎖怎麼辦？", groups=groups)

    assert groups == []
    assert request.user.groups == []


def test_playground_request_skips_grp_public_for_non_playground_tenant() -> None:
    activity = make_message_activity(
        channelId="playground",
        channelData={"tenant": {"id": "00000000-0000-0000-0000-000000000001"}},
    )
    groups = resolve_request_groups(activity)
    request = AgentRequest.from_activity(activity, "VPN 密碼被鎖怎麼辦？", groups=groups)

    assert groups == []
    assert request.user.groups == []
