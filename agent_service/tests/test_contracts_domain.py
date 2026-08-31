import json

import pytest
from pydantic import ValidationError

from agent_service.contracts import (
    AgentImage,
    AgentRequest,
    AgentResponse,
    Citation,
    ConversationIdentity,
    FeedbackRequest,
    Issue,
    IssueExtraction,
    IssueResult,
    MessageContent,
    Source,
    SourceImage,
    UserContext,
    UserIdentity,
)

# spec §6.2 structured output sample, verbatim.
SPEC_6_2_SAMPLE = """
{
  "issues": [
    {
      "id": 1,
      "description": "使用者無法登入 VPN",
      "isIT": true,
      "readiness": "NEED_MORE_INFO",
      "missingInfo": [
        "使用的 VPN 應用程式名稱",
        "畫面顯示的錯誤訊息或錯誤碼"
      ],
      "route": "KNOWLEDGE",
      "faqKey": null,
      "ticketAction": null
    }
  ]
}
"""


def test_issue_extraction_parses_spec_sample_verbatim() -> None:
    payload = json.loads(SPEC_6_2_SAMPLE)

    extraction = IssueExtraction.model_validate(payload)

    assert len(extraction.issues) == 1
    issue = extraction.issues[0]
    assert issue.id == 1
    assert issue.description == "使用者無法登入 VPN"
    assert issue.isIT is True
    assert issue.readiness == "NEED_MORE_INFO"
    assert issue.missingInfo == [
        "使用的 VPN 應用程式名稱",
        "畫面顯示的錯誤訊息或錯誤碼",
    ]
    assert issue.route == "KNOWLEDGE"
    assert issue.faqKey is None
    assert issue.ticketAction is None

    # Round-trip: re-serializing should reproduce the same structural data.
    round_tripped = json.loads(extraction.model_dump_json())
    assert round_tripped == payload


def test_missing_info_is_capped_at_two() -> None:
    issue = Issue(
        id=1,
        description="test",
        isIT=True,
        readiness="NEED_MORE_INFO",
        missingInfo=["a", "b", "c", "d"],
        route="KNOWLEDGE",
    )

    assert issue.missingInfo == ["a", "b"]


def test_missing_info_under_cap_is_untouched() -> None:
    issue = Issue(
        id=1,
        description="test",
        isIT=True,
        readiness="READY",
        missingInfo=["a"],
        route="KNOWLEDGE",
    )

    assert issue.missingInfo == ["a"]


@pytest.mark.parametrize(
    "field, value",
    [
        ("readiness", "MAYBE"),
        ("route", "MAGIC"),
    ],
)
def test_issue_rejects_invalid_enum_values(field: str, value: str) -> None:
    payload = {
        "id": 1,
        "description": "test",
        "isIT": True,
        "readiness": "READY",
        "missingInfo": [],
        "route": "KNOWLEDGE",
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        Issue.model_validate(payload)


def test_issue_result_rejects_invalid_result_type() -> None:
    with pytest.raises(ValidationError):
        IssueResult.model_validate({"issueId": 1, "resultType": "SOLVED"})


def test_issue_result_defaults() -> None:
    result = IssueResult(issueId=1, resultType="NO_KNOWLEDGE")

    assert result.answer == ""
    assert result.sources == []
    assert result.images == []
    assert result.questions == []
    assert result.ticketId is None
    assert result.backend is None
    assert result.error is None


def test_user_context_is_trusted_for_ticket_true() -> None:
    user = UserContext(
        entraObjectId="entra-1",
        displayName="Alice",
        email="alice@example.com",
    )

    assert user.is_trusted_for_ticket is True


def test_user_context_is_trusted_for_ticket_with_teams_id_only() -> None:
    user = UserContext(
        teamsUserId="teams-1",
        displayName="Alice",
        email="alice@example.com",
    )

    assert user.is_trusted_for_ticket is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"displayName": "Alice", "email": "alice@example.com"},  # missing stable id
        {"entraObjectId": "entra-1", "email": "alice@example.com"},  # missing name
        {"entraObjectId": "entra-1", "displayName": "Alice"},  # missing email
        {},  # nothing at all
    ],
)
def test_user_context_is_trusted_for_ticket_false(kwargs: dict) -> None:
    user = UserContext(**kwargs)

    assert user.is_trusted_for_ticket is False


def test_source_and_source_image_are_aliases() -> None:
    assert Source is Citation
    assert SourceImage is AgentImage


def test_feedback_request_valid_rating() -> None:
    feedback = FeedbackRequest(
        correlationId="corr-1",
        conversationId="conv-1",
        issueId=1,
        rating="UP",
        userId="user-1",
    )

    assert feedback.rating == "UP"


def test_feedback_request_rejects_invalid_rating() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest.model_validate(
            {
                "correlationId": "corr-1",
                "conversationId": None,
                "issueId": None,
                "rating": "MEH",
                "userId": None,
            }
        )


def _legacy_request_payload() -> dict:
    return {
        "requestId": "request-1",
        "channel": "msteams",
        "conversation": {
            "tenantId": "tenant-1",
            "conversationId": "conversation-1",
        },
        "user": {"entraObjectId": "user-1", "groups": []},
        "message": {
            "text": "VPN 密碼被鎖怎麼辦？",
            "locale": "zh-TW",
        },
    }


def test_agent_request_accepts_legacy_payload_shape() -> None:
    request = AgentRequest.model_validate(_legacy_request_payload())

    assert request.correlationId is None
    assert request.user.email is None


def test_agent_request_accepts_new_payload_shape() -> None:
    payload = _legacy_request_payload()
    payload["correlationId"] = "corr-123"
    payload["user"]["email"] = "user@example.com"

    request = AgentRequest.model_validate(payload)

    assert request.correlationId == "corr-123"
    assert request.user.email == "user@example.com"


def test_agent_request_direct_construction_still_works() -> None:
    request = AgentRequest(
        requestId="request-1",
        channel="msteams",
        conversation=ConversationIdentity(
            tenantId="tenant-1", conversationId="conversation-1"
        ),
        user=UserIdentity(entraObjectId="user-1"),
        message=MessageContent(text="hello"),
    )

    assert request.correlationId is None


def test_agent_response_backward_compatible_defaults() -> None:
    response = AgentResponse(answer="answer", traceId="trace-1")

    assert response.citations == []
    assert response.images == []
    assert response.correlationId is None
    assert response.issueResults == []
    assert response.feedbackEnabled is False
    assert response.estimatedCostUsd is None
    assert response.estimatedCostTwd is None
    assert response.costComplete is None


def test_agent_response_new_fields_round_trip() -> None:
    response = AgentResponse(
        answer="answer",
        traceId="trace-1",
        correlationId="corr-1",
        issueResults=[IssueResult(issueId=1, resultType="FAQ_ANSWERED", answer="ok")],
        feedbackEnabled=True,
    )
    dumped = response.model_dump()

    assert dumped["correlationId"] == "corr-1"
    assert dumped["feedbackEnabled"] is True
    assert dumped["issueResults"][0]["resultType"] == "FAQ_ANSWERED"
