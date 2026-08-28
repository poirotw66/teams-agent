from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from agent_service.contracts import (
    AgentRequest,
    ConversationIdentity,
    MessageContent,
    UserIdentity,
)
from agent_service.documents import DocumentChunk, DocumentImage
from agent_service.graph import RagAgent, message_text
from agent_service.retrieval import HybridIndex
from agent_service.settings import RagSettings


def make_settings(tmp_path: Path) -> RagSettings:
    return RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index.json",
        top_k=2,
        min_score=0.05,
        max_rewrites=0,
    )


def make_request(text: str) -> AgentRequest:
    return AgentRequest(
        requestId="request-1",
        channel="msteams",
        conversation=ConversationIdentity(
            tenantId="tenant-1",
            conversationId="conversation-1",
        ),
        user=UserIdentity(entraObjectId="user-1"),
        message=MessageContent(text=text, locale="zh-TW"),
    )


def test_message_text_extracts_google_content_blocks() -> None:
    message = AIMessage(content=[{"type": "text", "text": "純文字回答"}])

    assert message_text(message) == "純文字回答"


@pytest.mark.asyncio
async def test_offline_agent_returns_grounded_result(tmp_path: Path) -> None:
    index = HybridIndex(
        [
            DocumentChunk(
                chunk_id="vpn",
                title="VPN 常見問題",
                source_path="sources/vpn.md",
                content="VPN 密碼被鎖時，請聯繫資訊小幫手協助解鎖。",
                images=[
                    DocumentImage(
                        path="vpn/p01.png",
                        title="VPN 設定畫面",
                        alt_text="VPN 設定畫面",
                    )
                ],
            )
        ]
    )
    agent = RagAgent(make_settings(tmp_path), index)

    response = await agent.respond(make_request("VPN 密碼被鎖怎麼辦？"))

    assert "VPN 密碼被鎖" in response.answer
    assert response.citations[0].title == "VPN 常見問題"
    assert response.images[0].path == "vpn/p01.png"
    assert response.images[0].sourceChunkId == "vpn"
    assert response.traceId


@pytest.mark.asyncio
async def test_offline_agent_returns_no_answer_for_unrelated_query(
    tmp_path: Path,
) -> None:
    index = HybridIndex(
        [
            DocumentChunk(
                chunk_id="vpn",
                title="VPN",
                source_path="sources/vpn.md",
                content="VPN 密碼處理方式。",
            )
        ]
    )
    agent = RagAgent(make_settings(tmp_path), index)

    response = await agent.respond(make_request("今天午餐吃什麼？"))

    assert "沒有足夠資訊" in response.answer
    assert response.citations == []
