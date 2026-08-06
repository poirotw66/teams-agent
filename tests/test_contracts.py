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
            "images": [
                {
                    "path": "大州/p01.png",
                    "title": "大州操作畫面",
                    "altText": "IE 安全性設定",
                    "sourceChunkId": "chunk-8",
                }
            ],
        },
        fallback_trace_id="request-1",
    )

    formatted = format_agent_response(response)

    assert response.traceId == "trace-1"
    assert response.images[0].path == "大州/p01.png"
    assert "**來源**" in formatted
    assert "[API Key 申請流程](https://internal.example/docs/api-key)" in formatted


def test_agent_response_rejects_unsafe_image_path() -> None:
    response = AgentResponse.from_payload(
        {
            "answer": "ok",
            "images": [
                {
                    "path": "../secret.png",
                    "title": "unsafe",
                    "altText": "unsafe",
                    "sourceChunkId": "chunk-1",
                }
            ],
        },
        fallback_trace_id="request-1",
    )

    assert response.images == []


def test_agent_response_uses_request_id_when_trace_id_is_missing() -> None:
    response = AgentResponse.from_payload(
        {"answer": "ok"},
        fallback_trace_id="request-1",
    )

    assert response.traceId == "request-1"


def test_agent_request_generates_stable_correlation_id_matching_request_id() -> None:
    activity = Activity(
        type="message",
        channel_id="msteams",
        from_property=ChannelAccount(id="teams-user-1"),
        conversation=ConversationAccount(id="conversation-1"),
    )

    request = AgentRequest.from_activity(
        activity, "hello", correlation_id="fixed-correlation-id"
    )

    assert request.requestId == "fixed-correlation-id"
    assert request.correlationId == "fixed-correlation-id"
    assert request.to_payload()["correlationId"] == "fixed-correlation-id"


def test_agent_request_includes_email_and_groups() -> None:
    activity = Activity(
        type="message",
        channel_id="msteams",
        from_property=ChannelAccount(id="teams-user-1", aad_object_id="entra-1"),
        conversation=ConversationAccount(id="conversation-1"),
    )

    request = AgentRequest.from_activity(
        activity,
        "hello",
        correlation_id="c-1",
        email="justin@example.com",
        groups=["it-support"],
    )
    payload = request.to_payload()

    assert payload["user"]["email"] == "justin@example.com"
    assert payload["user"]["groups"] == ["it-support"]


def test_agent_response_parses_correlation_id_feedback_and_issue_results() -> None:
    response = AgentResponse.from_payload(
        {
            "answer": "ok",
            "traceId": "trace-1",
            "correlationId": "corr-1",
            "feedbackEnabled": True,
            "issueResults": [
                {"issueId": 1, "resultType": "FAQ_ANSWERED", "answer": "a"},
                {"issueId": 2, "resultType": "NEED_MORE_INFO"},
            ],
        },
        fallback_trace_id="request-1",
    )

    assert response.correlationId == "corr-1"
    assert response.feedbackEnabled is True
    assert [r.issueId for r in response.issueResults] == [1, 2]
    assert response.issueResults[0].feedback_eligible is True
    assert response.issueResults[1].feedback_eligible is False


def test_agent_response_defaults_when_new_fields_are_missing_or_malformed() -> None:
    response = AgentResponse.from_payload(
        {
            "answer": "ok",
            "correlationId": 12345,  # wrong type
            "feedbackEnabled": "yes",  # wrong type
            "issueResults": [
                "not-a-dict",
                {"issueId": "not-an-int", "resultType": "FAQ_ANSWERED"},
                {"issueId": 1},  # missing resultType
                {"issueId": 3, "resultType": "FAQ_ANSWERED"},
            ],
        },
        fallback_trace_id="request-1",
    )

    assert response.correlationId == "request-1"
    assert response.feedbackEnabled is False
    assert [r.issueId for r in response.issueResults] == [3]


def test_agent_response_from_payload_never_raises_on_garbage_top_level_fields() -> None:
    # Non-dict payload should still raise TypeError (documented contract),
    # but any dict shape -- even a totally malformed one -- must not raise
    # for the new optional fields.
    response = AgentResponse.from_payload(
        {"answer": "ok", "issueResults": "not-a-list"},
        fallback_trace_id="request-1",
    )

    assert response.issueResults == []
