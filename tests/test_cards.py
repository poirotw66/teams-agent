from teams_agent.cards import ADAPTIVE_CARD_CONTENT_TYPE, build_agent_activity
from teams_agent.contracts import AgentImage, AgentResponse, Citation
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
