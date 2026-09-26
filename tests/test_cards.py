from teams_agent.cards import (
    ADAPTIVE_CARD_CONTENT_TYPE,
    FEEDBACK_ACTION_MARKER,
    build_agent_activity,
)
from teams_agent.contracts import (
    AgentImage,
    AgentResponse,
    Citation,
    IssueResult,
    format_agent_response,
)
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
                releaseId="release-1",
            )
        ],
    )

    activity = build_agent_activity(response, settings, now=1_000)

    assert not isinstance(activity, str)
    assert activity.attachments
    assert activity.attachments[0].content_type == ADAPTIVE_CARD_CONTENT_TYPE
    body = activity.attachments[0].content["body"]
    image = next(item for item in body if item["type"] == "Image")
    assert image["url"].startswith(
        "https://bot.example.com/rag-assets/releases/release-1/"
    )


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


def test_response_with_citations_numbered_in_answer_prefixes_sources_with_matching_numbers() -> None:
    response = AgentResponse(
        answer="請登出 Teams 重新登入 [S1]。若密碼鎖定請至自助解鎖專區 [S2]。",
        traceId="trace-1",
        citations=[
            Citation(title="員工 IT 支援服務手冊", url="https://kb.example/handbook"),
            Citation(title="AD 帳號與系統解鎖 FAQ"),
        ],
    )

    formatted = format_agent_response(response)
    activity = build_agent_activity(response, AgentSettings())
    activity_text = (
        activity
        if isinstance(activity, str)
        else activity.attachments[0].content["body"][0]["text"]
    )

    assert "- [S1] [員工 IT 支援服務手冊](https://kb.example/handbook)" in formatted
    assert "- [S2] AD 帳號與系統解鎖 FAQ" in formatted
    assert "- [S1] [員工 IT 支援服務手冊](https://kb.example/handbook)" in activity_text
    assert "- [S2] AD 帳號與系統解鎖 FAQ" in activity_text


def test_format_agent_response_hides_policy_overlay_markers_and_sources() -> None:
    response = AgentResponse(
        answer=(
            "請調整安全性設定 [S1]。\n"
            "變更前請向權責單位確認 [POLICY-SEC-003]。\n"
            "> ⚠️ **系統資安政策提醒** [POLICY-SEC-003]：切勿擅自變更。"
        ),
        traceId="trace-1",
        citations=[
            Citation(title="大州操作說明", chunkId="chunk-1"),
            Citation(
                title="安全性設定變更確認原則 (POLICY-SEC-003)",
                chunkId="POLICY-SEC-003",
            ),
        ],
    )

    formatted = format_agent_response(response)

    assert "[S1]" in formatted
    assert "向權責單位確認" in formatted
    assert "POLICY-SEC-003" not in formatted
    assert "系統資安政策提醒" not in formatted
    assert "大州操作說明" in formatted
    assert "安全性設定變更確認原則" not in formatted


def test_card_adds_open_url_actions_for_citation_links_by_default() -> None:
    response = AgentResponse(
        answer="請調整安全性設定。",
        traceId="trace-1",
        citations=[
            Citation(
                title="大州系統_功能無法點選",
                url="https://bot.example.com/rag-sources/vpn.md",
                originalUrl="https://bot.example.com/rag-originals/src-1",
            )
        ],
        feedbackEnabled=True,
    )

    activity = build_agent_activity(
        response,
        AgentSettings(),
        conversation_id="conversation-1",
        now=1_000,
    )

    actions = activity.attachments[0].content["actions"]
    assert actions == [
        {
            "type": "Action.OpenUrl",
            "title": "開啟原始檔案：大州系統_功能無法點選",
            "url": "https://bot.example.com/rag-originals/src-1",
        },
        {
            "type": "Action.OpenUrl",
            "title": "查看引用段落：大州系統_功能無法點選",
            "url": "https://bot.example.com/rag-sources/vpn.md",
        },
    ]


def test_card_dedupes_source_buttons_for_same_document_chunks() -> None:
    response = AgentResponse(
        answer="請重新啟動安控元件。[S1][S2]",
        traceId="trace-1",
        citations=[
            Citation(
                title="樹精靈WEB-登入異常",
                url="https://bot.example.com/rag-citations/chunk-1",
                originalUrl="https://bot.example.com/rag-originals/web-1",
                sourcePath="sources/shu-web.md",
            ),
            Citation(
                title="樹精靈WEB-登入異常",
                url="https://bot.example.com/rag-citations/chunk-2",
                originalUrl="https://bot.example.com/rag-originals/web-1",
                sourcePath="sources/shu-web.md",
            ),
        ],
        feedbackEnabled=True,
    )

    activity = build_agent_activity(
        response,
        AgentSettings(),
        conversation_id="conversation-1",
        now=1_000,
    )

    actions = activity.attachments[0].content["actions"]
    assert actions == [
        {
            "type": "Action.OpenUrl",
            "title": "開啟原始檔案：樹精靈WEB-登入異常",
            "url": "https://bot.example.com/rag-originals/web-1",
        },
        {
            "type": "Action.OpenUrl",
            "title": "查看引用段落：樹精靈WEB-登入異常",
            "url": "https://bot.example.com/rag-citations/chunk-1",
        },
    ]


def test_card_adds_open_url_actions_for_citation_links() -> None:
    response = AgentResponse(
        answer="請調整安全性設定。",
        traceId="trace-1",
        citations=[Citation(title="大州系統_功能無法點選", url="https://bot.example.com/rag-sources/vpn.md")],
        feedbackEnabled=True,
    )

    activity = build_agent_activity(
        response,
        AgentSettings(citation_open_actions_enabled=True),
        conversation_id="conversation-1",
        now=1_000,
    )

    actions = activity.attachments[0].content["actions"]
    assert actions == [
        {
            "type": "Action.OpenUrl",
            "title": "大州系統_功能無法點選",
            "url": "https://bot.example.com/rag-sources/vpn.md",
        }
    ]


def test_card_adds_open_url_action_for_answer_body_url() -> None:
    unlock_url = (
        "https://teams-ai-ops-backoffice-jt7pjdeeoa-de.a.run.app"
        "/static/demo/ad-unlock/index.html"
    )
    response = AgentResponse(
        answer=(
            "問題：AD帳號解鎖\n\n"
            "處理方式：\n"
            f"請至 AD 自助解鎖專區：{unlock_url} [S1]。"
        ),
        traceId="trace-1",
        correlationId="corr-1",
        citations=[Citation(title="AD 帳號與系統解鎖 FAQ")],
        feedbackEnabled=True,
        issueResults=[IssueResult(issueId=1, resultType="FAQ_ANSWERED")],
    )

    activity = build_agent_activity(
        response, AgentSettings(), conversation_id="conversation-1"
    )

    assert not isinstance(activity, str)
    text = activity.attachments[0].content["body"][0]["text"]
    assert f"[{unlock_url}]({unlock_url})" in text
    actions = activity.attachments[0].content["actions"]
    assert actions == [
        {
            "type": "Action.OpenUrl",
            "title": "開啟 AD 自助解鎖專區",
            "url": unlock_url,
        }
    ]
