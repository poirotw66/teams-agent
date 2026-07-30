import asyncio

import pytest

from teams_agent.agent_gateway import AgentGateway, AgentGatewayError
from teams_agent.contracts import (
    AgentRequest,
    ConversationIdentity,
    MessageContent,
    UserIdentity,
)
from teams_agent.settings import AgentSettings


def make_request() -> AgentRequest:
    return AgentRequest(
        requestId="request-1",
        channel="msteams",
        conversation=ConversationIdentity(conversationId="conversation-1"),
        user=UserIdentity(teamsUserId="user-1"),
        message=MessageContent(text="hello", locale="zh-TW"),
    )


@pytest.mark.asyncio
async def test_echo_mode_does_not_call_transport() -> None:
    async def unexpected_transport(*_args):
        raise AssertionError("Transport should not be called in Echo mode.")

    gateway = AgentGateway(AgentSettings(), transport=unexpected_transport)

    response = await gateway.answer(make_request())

    assert response.answer == "收到：hello"
    assert response.traceId == "request-1"


@pytest.mark.asyncio
async def test_api_mode_sends_contract_and_bearer_token() -> None:
    captured = {}

    async def fake_transport(url, payload, headers, timeout):
        captured.update(
            url=url,
            payload=payload,
            headers=headers,
            timeout=timeout,
        )
        return {"answer": "Agent answer", "traceId": "trace-1"}

    gateway = AgentGateway(
        AgentSettings(
            mode="api",
            api_url="https://agent.example/chat",
            api_token="internal-token",
            api_auth_mode="service_token",
            api_timeout_seconds=5,
        ),
        transport=fake_transport,
    )

    response = await gateway.answer(make_request())

    assert captured["url"] == "https://agent.example/chat"
    assert captured["payload"]["requestId"] == "request-1"
    assert captured["headers"]["Authorization"] == "Bearer internal-token"
    assert captured["timeout"] == 5
    assert response.answer == "Agent answer"


@pytest.mark.asyncio
async def test_api_mode_sends_google_identity_token() -> None:
    captured = {}

    async def fake_transport(url, payload, headers, timeout):
        captured.update(headers=headers)
        return {"answer": "Agent answer", "traceId": "trace-1"}

    async def fake_identity_token_provider(audience: str) -> str:
        assert audience == "https://agent.example"
        return "google-identity-token"

    gateway = AgentGateway(
        AgentSettings(
            mode="api",
            api_url="https://agent.example/agent/chat",
            api_auth_mode="google_id_token",
        ),
        transport=fake_transport,
        identity_token_provider=fake_identity_token_provider,
    )

    await gateway.answer(make_request())

    assert captured["headers"]["Authorization"] == "Bearer google-identity-token"


@pytest.mark.asyncio
async def test_api_timeout_is_converted_to_gateway_error() -> None:
    async def timeout_transport(*_args):
        raise asyncio.TimeoutError

    gateway = AgentGateway(
        AgentSettings(mode="api", api_url="https://agent.example/chat"),
        transport=timeout_transport,
    )

    with pytest.raises(AgentGatewayError, match="request failed"):
        await gateway.answer(make_request())
