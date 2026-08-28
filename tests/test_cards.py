from teams_agent.cards import (
    ADAPTIVE_CARD_CONTENT_TYPE,
    FEEDBACK_ACTION_MARKER,
    build_agent_activity,
)
from teams_agent.contracts import AgentImage, AgentResponse, Citation, IssueResult
from teams_agent.settings import AgentSettings


def test_response_with_image_builds_adaptive_card(tmp_path) -> None:
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    settings = AgentSettings(
        asset_dir=asset_dir,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )
    response = AgentResponse(
        answer="請調整安全性設定。[S1]",
        traceId="trace-1",
        citations=[Citation(title="大州操作說明")],
        images=[
            AgentImage(
                path="大州/p01.png",
                title="大州操作畫面",
                altText="IE 安全性設定",
                sourceChunkId="chunk-1",
            )
        ],
    )

    activity = build_agent_activity(response, settings, now=1_000)

    assert not isinstance(activity, str)
    assert activity.attachments
    assert activity.attachments[0].content_type == ADAPTIVE_CARD_CONTENT_TYPE
    body = activity.attachments[0].content["body"]
    image = next(item for item in body if item["type"] == "Image")
    assert image["url"].startswith("https://bot.example.com/rag-assets/")


def test_response_without_image_remains_plain_text() -> None:
    response = AgentResponse(answer="純文字回答", traceId="trace-1")

    activity = build_agent_activity(response, AgentSettings())

    assert activity == "純文字回答"


def test_response_with_citations_and_no_feedback_still_formats_sources() -> None:
    # feedbackEnabled is False here, so format_agent_response's own citation
    # rendering must be exactly what comes back (spec requirement D).
    response = AgentResponse(
        answer="請重新登入 Microsoft 365 帳號。",
        traceId="trace-1",
        citations=[Citation(title="FAQ")],
    )

    activity = build_agent_activity(response, AgentSettings())

    assert isinstance(activity, str)
    assert "**來源**" in activity
    assert "- FAQ" in activity


def test_feedback_enabled_without_images_builds_card_with_sources_and_actions() -> None:
    response = AgentResponse(
        answer="請重新登入 Microsoft 365 帳號。",
        traceId="trace-1",
        correlationId="corr-1",
        citations=[Citation(title="FAQ")],
        feedbackEnabled=True,
        issueResults=[IssueResult(issueId=7, resultType="FAQ_ANSWERED")],
    )

    activity = build_agent_activity(
        response, AgentSettings(), conversation_id="conversation-1"
    )

    assert not isinstance(activity, str)
    body = activity.attachments[0].content["body"]
    text_block = body[0]
    assert "**來源**" in text_block["text"]
    assert "- FAQ" in text_block["text"]

    action_set = next(item for item in body if item["type"] == "ActionSet")
    actions = action_set["actions"]
    assert len(actions) == 2
    up, down = actions
    assert up["data"] == {
        FEEDBACK_ACTION_MARKER: True,
        "correlationId": "corr-1",
        "conversationId": "conversation-1",
        "issueId": 7,
        "rating": "UP",
    }
    assert down["data"]["rating"] == "DOWN"
    assert down["data"]["issueId"] == 7


def test_feedback_enabled_without_conversation_id_falls_back_to_plain_text() -> None:
    response = AgentResponse(
        answer="純文字回答",
        traceId="trace-1",
        feedbackEnabled=True,
        issueResults=[IssueResult(issueId=1, resultType="FAQ_ANSWERED")],
    )

    activity = build_agent_activity(response, AgentSettings(), conversation_id=None)

    assert activity == "純文字回答"


def test_feedback_only_rendered_for_answered_issues() -> None:
    response = AgentResponse(
        answer="a",
        traceId="trace-1",
        feedbackEnabled=True,
        issueResults=[
            IssueResult(issueId=1, resultType="NEED_MORE_INFO"),
            IssueResult(issueId=2, resultType="KNOWLEDGE_ANSWERED"),
        ],
    )

    activity = build_agent_activity(
        response, AgentSettings(), conversation_id="conversation-1"
    )

    body = activity.attachments[0].content["body"]
    action_sets = [item for item in body if item["type"] == "ActionSet"]
    assert len(action_sets) == 1
    assert action_sets[0]["actions"][0]["data"]["issueId"] == 2


def test_feedback_with_no_issue_results_uses_default_issue_id() -> None:
    response = AgentResponse(
        answer="a",
        traceId="trace-1",
        feedbackEnabled=True,
    )

    activity = build_agent_activity(
        response, AgentSettings(), conversation_id="conversation-1"
    )

    body = activity.attachments[0].content["body"]
    action_set = next(item for item in body if item["type"] == "ActionSet")
    assert action_set["actions"][0]["data"]["issueId"] == 1


def test_feedback_with_images_still_renders_images_sources_and_actions(
    tmp_path,
) -> None:
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    settings = AgentSettings(
        asset_dir=asset_dir,
        public_base_url="https://bot.example.com",
        asset_signing_key="test-signing-key-long-enough",
    )
    response = AgentResponse(
        answer="請調整安全性設定。",
        traceId="trace-1",
        citations=[Citation(title="大州操作說明")],
        images=[
            AgentImage(
                path="大州/p01.png",
                title="大州操作畫面",
                altText="IE 安全性設定",
                sourceChunkId="chunk-1",
            )
        ],
        feedbackEnabled=True,
        issueResults=[IssueResult(issueId=1, resultType="KNOWLEDGE_ANSWERED")],
    )

    activity = build_agent_activity(
        response, settings, conversation_id="conversation-1", now=1_000
    )

    body = activity.attachments[0].content["body"]
    assert any(item["type"] == "Image" for item in body)
    assert any(
        item["type"] == "TextBlock" and "**來源**" in item.get("text", "")
        for item in body
    )
    assert any(item["type"] == "ActionSet" for item in body)
