
import json

import pytest

from teams_agent import agent_gateway as agent_gateway_module
from teams_agent.agent_gateway import (
    AgentGateway,
    AgentGatewayError,
    parse_sse_block,
)
from teams_agent.contracts import (
    AgentRequest,
    ConversationIdentity,
    FeedbackRequest,
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
        correlationId="request-1",
    )


@pytest.mark.asyncio
async def test_echo_mode_does_not_call_transport() -> None:
    async def unexpected_transport(*_args):
        raise AssertionError("Transport should not be called in Echo mode.")

    gateway = AgentGateway(AgentSettings(), transport=unexpected_transport)

    response = await gateway.answer(make_request())

    assert response.answer == "收到：hello"
    assert response.traceId == "request-1"
    assert response.correlationId == "request-1"


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
    assert captured["payload"]["correlationId"] == "request-1"
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
        raise TimeoutError

    gateway = AgentGateway(
        AgentSettings(mode="api", api_url="https://agent.example/chat"),
        transport=timeout_transport,
    )

    with pytest.raises(AgentGatewayError, match="request failed"):
        await gateway.answer(make_request())


def make_feedback() -> FeedbackRequest:
    return FeedbackRequest(
        correlationId="corr-1",
        conversationId="conversation-1",
        issueId=2,
        rating="UP",
        userId="user-1",
    )


@pytest.mark.asyncio
async def test_send_feedback_posts_to_feedback_endpoint_with_bearer_token() -> None:
    captured = {}

    async def fake_transport(url, payload, headers, timeout):
        captured.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {"status": "ok"}

    gateway = AgentGateway(
        AgentSettings(
            mode="api",
            api_url="https://agent.example/agent/chat",
            api_token="internal-token",
            api_auth_mode="service_token",
            api_timeout_seconds=5,
        ),
        transport=fake_transport,
    )

    await gateway.send_feedback(make_feedback())

    assert captured["url"] == "https://agent.example/feedback"
    assert captured["payload"] == {
        "correlationId": "corr-1",
        "conversationId": "conversation-1",
        "issueId": 2,
        "rating": "UP",
        "userId": "user-1",
    }
    assert captured["headers"]["Authorization"] == "Bearer internal-token"


@pytest.mark.asyncio
async def test_send_feedback_is_noop_in_echo_mode() -> None:
    async def unexpected_transport(*_args):
        raise AssertionError("Transport should not be called in Echo mode.")

    gateway = AgentGateway(AgentSettings(), transport=unexpected_transport)

    await gateway.send_feedback(make_feedback())


@pytest.mark.asyncio
async def test_send_feedback_raises_gateway_error_on_transport_failure() -> None:
    async def failing_transport(*_args):
        raise TimeoutError

    gateway = AgentGateway(
        AgentSettings(mode="api", api_url="https://agent.example/agent/chat"),
        transport=failing_transport,
    )

    with pytest.raises(AgentGatewayError, match="Feedback submission failed"):
        await gateway.send_feedback(make_feedback())


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}"


def streaming_settings(**overrides) -> AgentSettings:
    defaults = {
        "mode": "api",
        "api_url": "https://agent.example/agent/chat",
    }
    defaults.update(overrides)
    return AgentSettings(**defaults)


def make_stream_transport(blocks: list[str]):
    async def transport(url, payload, headers, timeout):
        transport.calls.append({"url": url, "headers": headers, "timeout": timeout})
        for block in blocks:
            yield block

    transport.calls = []
    return transport


@pytest.mark.asyncio
async def test_answer_stream_yields_stages_then_the_response() -> None:
    transport = make_stream_transport(
        [
            sse("stage", {"label": "已收到你的問題…"}),
            sse("stage", {"label": "正在檢索知識庫…"}),
            sse("response", {"answer": "重設密碼即可。", "traceId": "trace-1"}),
        ]
    )
    gateway = AgentGateway(streaming_settings(), stream_transport=transport)

    events = [event async for event in gateway.answer_stream(make_request())]

    assert [kind for kind, _ in events] == ["stage", "stage", "response"]
    assert [value for kind, value in events if kind == "stage"] == [
        "已收到你的問題…",
        "正在檢索知識庫…",
    ]
    assert events[-1][1].answer == "重設密碼即可。"
    # The stream endpoint is derived from api_url, never configured apart.
    assert transport.calls[0]["url"] == "https://agent.example/agent/chat/stream"


@pytest.mark.asyncio
async def test_answer_stream_sends_the_service_token() -> None:
    transport = make_stream_transport(
        [sse("response", {"answer": "ok", "traceId": "t"})]
    )
    gateway = AgentGateway(
        streaming_settings(api_token="internal-token", api_auth_mode="service_token"),
        stream_transport=transport,
    )

    [_ async for _ in gateway.answer_stream(make_request())]

    assert transport.calls[0]["headers"]["Authorization"] == "Bearer internal-token"


@pytest.mark.asyncio
async def test_answer_stream_raises_on_an_error_event() -> None:
    transport = make_stream_transport(
        [
            sse("stage", {"label": "正在檢索知識庫…"}),
            sse("error", {"detail": "unavailable", "correlationId": "c-1"}),
        ]
    )
    gateway = AgentGateway(streaming_settings(), stream_transport=transport)

    with pytest.raises(AgentGatewayError):
        [_ async for _ in gateway.answer_stream(make_request())]


@pytest.mark.asyncio
async def test_answer_stream_raises_when_the_stream_ends_without_a_response() -> None:
    # Progress but no answer must not look like success, or the user would be
    # left with status text and nothing else.
    transport = make_stream_transport([sse("stage", {"label": "正在檢索知識庫…"})])
    gateway = AgentGateway(streaming_settings(), stream_transport=transport)

    with pytest.raises(AgentGatewayError, match="without a response"):
        [_ async for _ in gateway.answer_stream(make_request())]


@pytest.mark.asyncio
async def test_answer_stream_skips_unparseable_blocks() -> None:
    transport = make_stream_transport(
        [
            ": keep-alive",
            "event: stage\ndata: {not json",
            sse("unknown-event", {"label": "ignored"}),
            sse("stage", {"label": ""}),
            sse("response", {"answer": "ok", "traceId": "t"}),
        ]
    )
    gateway = AgentGateway(streaming_settings(), stream_transport=transport)

    events = [event async for event in gateway.answer_stream(make_request())]

    assert [kind for kind, _ in events] == ["response"]


@pytest.mark.asyncio
async def test_answer_stream_refuses_when_streaming_is_disabled() -> None:
    gateway = AgentGateway(streaming_settings(streaming_enabled=False))

    with pytest.raises(AgentGatewayError, match="not configured"):
        [_ async for _ in gateway.answer_stream(make_request())]


@pytest.mark.asyncio
async def test_answer_stream_refuses_in_echo_mode() -> None:
    gateway = AgentGateway(AgentSettings())

    with pytest.raises(AgentGatewayError, match="not configured"):
        [_ async for _ in gateway.answer_stream(make_request())]


def test_parse_sse_block_handles_multi_line_data() -> None:
    assert parse_sse_block('event: stage\ndata: {"label":\ndata:  "hi"}') == (
        "stage",
        {"label": "hi"},
    )


def test_parse_sse_block_rejects_non_object_payloads() -> None:
    assert parse_sse_block("event: stage\ndata: [1, 2]") is None


class FakeContent:
    """Mimics aiohttp's `response.content.iter_any()` over fixed-size chunks."""

    def __init__(self, body: bytes, chunk_size: int) -> None:
        self._body = body
        self._chunk_size = chunk_size

    async def iter_any(self):
        for start in range(0, len(self._body), self._chunk_size):
            yield self._body[start : start + self._chunk_size]


class FakeResponse:
    status = 200

    def __init__(self, body: bytes, chunk_size: int) -> None:
        self.content = FakeContent(body, chunk_size)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class FakeSession:
    def __init__(self, body: bytes, chunk_size: int) -> None:
        self._body = body
        self._chunk_size = chunk_size

    def post(self, *_args, **_kwargs):
        return FakeResponse(self._body, self._chunk_size)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 7, 64])
async def test_stream_transport_survives_chunks_splitting_a_utf8_character(
    monkeypatch, chunk_size
) -> None:
    # Raw (unescaped) Chinese on the wire: a chunk boundary lands inside a
    # 3-byte character, which a per-chunk decode would mangle.
    body = (
        'event: stage\ndata: {"label": "正在檢索知識庫…"}\n\n'
        'event: response\ndata: {"answer": "重設密碼即可。", "traceId": "t-1"}\n\n'
    ).encode()
    monkeypatch.setattr(
        agent_gateway_module,
        "ClientSession",
        lambda **_kwargs: FakeSession(body, chunk_size),
    )

    blocks = [
        block
        async for block in agent_gateway_module.aiohttp_stream_transport(
            "https://agent.example/agent/chat/stream", {}, {}, 10.0
        )
    ]

    parsed = [parse_sse_block(block) for block in blocks]
    assert parsed == [
        ("stage", {"label": "正在檢索知識庫…"}),
        ("response", {"answer": "重設密碼即可。", "traceId": "t-1"}),
    ]
    assert "�" not in "".join(blocks)
