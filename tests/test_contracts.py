from microsoft_teams.api import MessageActivity

from teams_agent.contracts import (
    AgentRequest,
    AgentResponse,
    format_agent_response,
)


def make_message_activity(**overrides) -> MessageActivity:
    """Build a MessageActivity the way the Teams SDK deserializes one.

    `model_validate` (rather than the constructor) is used so the camelCase
    `channelData` payload goes through the same alias-driven parsing path the
    SDK uses on a real inbound activity.
    """
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


def test_agent_request_reads_evaluation_knowledge_backend_from_channel_data() -> None:
    activity = make_message_activity(
        channelId="playground",
        channelData={
            "tenant": {"id": "tenant-1"},
            "evaluationKnowledgeBackend": "GEMINI_FILE_SEARCH",
        },
    )

    request = AgentRequest.from_activity(activity, "VPN 問題")
    payload = request.to_payload()

    assert request.channel == "playground"
    assert payload["evaluationKnowledgeBackend"] == "GEMINI_FILE_SEARCH"


def test_agent_request_ignores_invalid_evaluation_knowledge_backend() -> None:
    activity = make_message_activity(
        channelData={
            "tenant": {"id": "tenant-1"},
            "evaluationKnowledgeBackend": "PINECONE",
        },
    )

    payload = AgentRequest.from_activity(activity, "hello").to_payload()

    assert payload["evaluationKnowledgeBackend"] is None


def test_agent_request_extracts_teams_context() -> None:
    activity = make_message_activity(
        channelData={
            "tenant": {"id": "tenant-1"},
            "team": {"id": "team-1"},
            "channel": {"id": "channel-1"},
        },
        locale="zh-TW",
        **{
            "from": {
                "id": "teams-user-1",
                "name": "Justin",
                "aadObjectId": "entra-user-1",
            }
        },
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


def test_agent_request_handles_personal_scope_without_team_or_channel() -> None:
    # A 1:1 personal chat carries no team/channel in channelData; the tenant
    # id then only comes off the sender account.
    activity = make_message_activity(
        channelData={"tenant": {"id": "tenant-1"}},
        **{"from": {"id": "teams-user-1", "tenantId": "tenant-from-account"}},
    )

    payload = AgentRequest.from_activity(activity, "hello").to_payload()

    assert payload["conversation"] == {
        "tenantId": "tenant-1",
        "teamId": None,
        "channelId": None,
        "conversationId": "conversation-1",
    }


def test_agent_request_falls_back_to_sender_tenant_without_channel_data() -> None:
    activity = make_message_activity(
        **{"from": {"id": "teams-user-1", "tenantId": "tenant-from-account"}}
    )

    payload = AgentRequest.from_activity(activity, "hello").to_payload()

    assert payload["conversation"]["tenantId"] == "tenant-from-account"


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


def test_format_agent_response_includes_turn_cost_footer() -> None:
    response = AgentResponse(
        answer="請重新登入 Microsoft 365 帳號。",
        traceId="trace-1",
        estimatedCostUsd=0.00064050,
        estimatedCostTwd=0.020,
        costComplete=True,
    )

    formatted = format_agent_response(response)

    assert formatted.endswith("_預估成本：$0.00064050 USD / $0.020 TWD_")


def test_format_agent_response_shows_incomplete_cost_notice() -> None:
    response = AgentResponse(
        answer="請重新登入 Microsoft 365 帳號。",
        traceId="trace-1",
        estimatedCostUsd=None,
        costComplete=False,
    )

    formatted = format_agent_response(response)

    assert "無法估算" in formatted


def test_agent_response_from_payload_reads_turn_cost_fields() -> None:
    response = AgentResponse.from_payload(
        {
            "answer": "ok",
            "estimatedCostUsd": 0.00042,
            "estimatedCostTwd": 0.013,
            "costComplete": True,
        },
        fallback_trace_id="request-1",
    )

    assert response.estimatedCostUsd == 0.00042
    assert response.estimatedCostTwd == 0.013
    assert response.costComplete is True


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
    activity = make_message_activity()

    request = AgentRequest.from_activity(
        activity, "hello", correlation_id="fixed-correlation-id"
    )

    assert request.requestId == "fixed-correlation-id"
    assert request.correlationId == "fixed-correlation-id"
    assert request.to_payload()["correlationId"] == "fixed-correlation-id"


def test_agent_request_includes_email_and_groups() -> None:
    activity = make_message_activity(
        **{"from": {"id": "teams-user-1", "aadObjectId": "entra-1"}}
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
