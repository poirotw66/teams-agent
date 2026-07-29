from microsoft_agents.activity import Activity, ChannelAccount, ConversationAccount

from teams_agent.contracts import (
    AgentRequest,
    AgentResponse,
    format_agent_response,
)


def test_agent_request_extracts_teams_context() -> None:
    activity = Activity(
        type="message",
        channel_id="msteams",
        channel_data={
            "tenant": {"id": "tenant-1"},
            "team": {"id": "team-1"},
            "channel": {"id": "channel-1"},
        },
        from_property=ChannelAccount(
            id="teams-user-1",
            name="Justin",
            aad_object_id="entra-user-1",
        ),
        conversation=ConversationAccount(id="conversation-1"),
        locale="zh-TW",
    )

    request = AgentRequest.from_activity(activity, "如何申請 API Key？")
    payload = request.to_payload()

    assert request.channel == "msteams"
    assert payload["conversation"] == {
        "tenantId": "tenant-1",
        "teamId": "team-1",
        "channelId": "channel-1",
        "conversationId": "conversation-1",
    }
    assert payload["user"]["entraObjectId"] == "entra-user-1"
    assert payload["message"] == {
        "text": "如何申請 API Key？",
        "locale": "zh-TW",
    }


def test_agent_response_formats_citations() -> None:
    response = AgentResponse.from_payload(
        {
            "answer": "請至內部平台提出申請。",
            "traceId": "trace-1",
            "citations": [
                {
                    "title": "API Key 申請流程",
                    "url": "https://internal.example/docs/api-key",
                    "chunkId": "chunk-8",
                }
            ],
        },
        fallback_trace_id="request-1",
    )

    formatted = format_agent_response(response)

    assert response.traceId == "trace-1"
    assert "**來源**" in formatted
    assert "[API Key 申請流程](https://internal.example/docs/api-key)" in formatted


def test_agent_response_uses_request_id_when_trace_id_is_missing() -> None:
    response = AgentResponse.from_payload(
        {"answer": "ok"},
        fallback_trace_id="request-1",
    )

    assert response.traceId == "request-1"

