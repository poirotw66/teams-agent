"""Streaming orchestration in `teams_agent.agent`.

Covers which turns stream, and what the user ends up with when streaming
fails at each of the points it can fail.
"""

import os

import pytest

os.environ.setdefault("DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS", "true")

from microsoft_teams.api import MessageActivity
from microsoft_teams.apps.plugins import (
    StreamNotAllowedError,
    StreamTimedOutError,
)

from teams_agent import agent as agent_module
from teams_agent.agent_gateway import AgentGatewayError
from teams_agent.contracts import (
    AgentRequest,
    AgentResponse,
    ConversationIdentity,
    MessageContent,
    UserIdentity,
)
from teams_agent.settings import AgentSettings


def test_welcome_message_matches_actual_mode() -> None:
    assert "Echo 測試模式" in agent_module._welcome_message("echo")
    api_message = agent_module._welcome_message("api")
    assert "企業知識庫" in api_message
    assert "Echo" not in api_message


class FakeStream:
    """Records what the handler did to the stream, in order."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self._fail_with = fail_with

    def _maybe_fail(self) -> None:
        if self._fail_with is not None:
            raise self._fail_with

    def update(self, text: str) -> None:
        self.calls.append(("update", text))
        self._maybe_fail()

    def clear_text(self) -> None:
        self.calls.append(("clear_text", None))

    def emit(self, activity) -> None:
        self.calls.append(("emit", activity))

    async def close(self):
        self.calls.append(("close", None))


class FakeContext:
    def __init__(self, conversation_type: str = "personal", stream: FakeStream | None = None):
        self.activity = MessageActivity.model_validate(
            {
                "type": "message",
                "id": "activity-1",
                "channelId": "msteams",
                "from": {"id": "user-1"},
                "recipient": {"id": "bot-1"},
                "conversation": {
                    "id": "conversation-1",
                    "conversationType": conversation_type,
                },
                "text": "hello",
            }
        )
        self.stream = stream or FakeStream()
        self.sent: list[object] = []

    async def send(self, activity):
        self.sent.append(activity)


def make_request() -> AgentRequest:
    return AgentRequest(
        requestId="request-1",
        channel="msteams",
        conversation=ConversationIdentity(conversationId="conversation-1"),
        user=UserIdentity(teamsUserId="user-1"),
        message=MessageContent(text="hello"),
        correlationId="request-1",
    )


API_SETTINGS = AgentSettings(mode="api", api_url="https://agent.example/agent/chat")


@pytest.fixture
def api_mode(monkeypatch):
    monkeypatch.setattr(agent_module, "agent_settings", API_SETTINGS)
    return API_SETTINGS


def stub_stream(events, error: Exception | None = None):
    async def answer_stream(_request):
        for event in events:
            yield event
        if error is not None:
            raise error

    return answer_stream


def install_gateway(monkeypatch, answer_stream=None, answer=None):
    class FakeGateway:
        pass

    gateway = FakeGateway()
    if answer_stream is not None:
        gateway.answer_stream = answer_stream
    if answer is not None:
        gateway.answer = answer
    monkeypatch.setattr(agent_module, "agent_gateway", gateway)
    return gateway


# --- which turns stream -------------------------------------------------


def test_personal_chat_streams(api_mode) -> None:
    assert agent_module._streaming_supported(FakeContext("personal")) is True


@pytest.mark.parametrize("conversation_type", ["channel", "groupChat"])
def test_channels_and_group_chats_do_not_stream(api_mode, conversation_type) -> None:
    # Teams rejects streamed messages outside 1:1 chats, and this bot installs
    # to a team by default -- so this is the common case, not an edge case.
    assert agent_module._streaming_supported(FakeContext(conversation_type)) is False


def test_echo_mode_does_not_stream(monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "agent_settings", AgentSettings())

    assert agent_module._streaming_supported(FakeContext("personal")) is False


def test_streaming_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_module,
        "agent_settings",
        AgentSettings(
            mode="api",
            api_url="https://agent.example/agent/chat",
            streaming_enabled=False,
        ),
    )

    assert agent_module._streaming_supported(FakeContext("personal")) is False


# --- the happy path -----------------------------------------------------


@pytest.mark.asyncio
async def test_stages_are_streamed_and_the_card_closes_the_stream(
    api_mode, monkeypatch
) -> None:
    response = AgentResponse(answer="重設密碼即可。", traceId="t-1")
    install_gateway(
        monkeypatch,
        answer_stream=stub_stream(
            [("stage", "已收到你的問題…"), ("stage", "正在檢索…"), ("response", response)]
        ),
    )
    ctx = FakeContext("personal")

    delivered = await agent_module._answer_streaming(ctx, make_request(), "c-1")

    assert delivered is True
    kinds = [name for name, _ in ctx.stream.calls]
    # Progress, then the accumulated text is dropped so the final activity
    # replaces it rather than stacking under it, then close.
    assert kinds == ["update", "update", "clear_text", "emit", "close"]
    assert [text for name, text in ctx.stream.calls if name == "update"] == [
        "已收到你的問題…",
        "正在檢索…",
    ]
    assert ctx.sent == []


# --- failure paths ------------------------------------------------------


@pytest.mark.asyncio
async def test_teams_refusing_mid_flight_falls_back_to_a_plain_reply(
    api_mode, monkeypatch
) -> None:
    install_gateway(
        monkeypatch, answer_stream=stub_stream([("stage", "已收到你的問題…")])
    )
    ctx = FakeContext("personal", stream=FakeStream(fail_with=StreamNotAllowedError()))

    delivered = await agent_module._answer_streaming(ctx, make_request(), "c-1")

    # Nothing reached the user, so the caller must retry without streaming.
    assert delivered is False
    assert ctx.sent == []


@pytest.mark.asyncio
async def test_gateway_failure_mid_stream_becomes_the_standard_error_reply(
    api_mode, monkeypatch
) -> None:
    install_gateway(
        monkeypatch,
        answer_stream=stub_stream(
            [("stage", "已收到你的問題…")], error=AgentGatewayError("boom")
        ),
    )
    ctx = FakeContext("personal")

    delivered = await agent_module._answer_streaming(ctx, make_request(), "c-1")

    assert delivered is True
    emitted = [value for name, value in ctx.stream.calls if name == "emit"]
    assert len(emitted) == 1
    assert "暫時無法回應" in emitted[0]
    assert "c-1" in emitted[0]


@pytest.mark.asyncio
async def test_a_dead_stream_delivers_the_error_as_a_normal_message(
    api_mode, monkeypatch
) -> None:
    class DeadStream(FakeStream):
        def emit(self, activity):
            raise StreamTimedOutError()

    install_gateway(
        monkeypatch,
        answer_stream=stub_stream([], error=AgentGatewayError("boom")),
    )
    ctx = FakeContext("personal", stream=DeadStream())

    delivered = await agent_module._answer_streaming(ctx, make_request(), "c-1")

    assert delivered is True
    assert len(ctx.sent) == 1
    assert "暫時無法回應" in ctx.sent[0]


@pytest.mark.asyncio
async def test_a_cancelled_stream_is_not_re_answered(api_mode, monkeypatch) -> None:
    # The user pressed Stop, or Teams hit its two-minute streaming limit.
    # Partial output is already on screen; re-answering would duplicate it.
    install_gateway(
        monkeypatch,
        answer_stream=stub_stream([], error=StreamTimedOutError()),
    )
    ctx = FakeContext("personal")

    delivered = await agent_module._answer_streaming(ctx, make_request(), "c-1")

    assert delivered is True
    assert ctx.sent == []


# --- commands survive being @mentioned ----------------------------------


def mention_activity(text: str, scope: str) -> MessageActivity:
    """A channel message as Teams actually delivers it: mention still in text."""
    return MessageActivity.model_validate(
        {
            "type": "message",
            "id": "activity-1",
            "channelId": "msteams",
            "from": {"id": "user-1"},
            "recipient": {"id": "bot-1", "name": "TeamsAgent"},
            "conversation": {"id": "conversation-1", "conversationType": scope},
            "text": f"<at>TeamsAgent</at> {text}",
            "entities": [
                {
                    "type": "mention",
                    "text": "<at>TeamsAgent</at>",
                    "mentioned": {"id": "bot-1", "name": "TeamsAgent"},
                }
            ],
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["channel", "groupChat"])
async def test_help_works_when_the_bot_is_mentioned(monkeypatch, scope) -> None:
    # Regression: /help used to go through on_message_pattern, which matches
    # the raw activity text -- "<at>TeamsAgent</at> /help" never matched the
    # anchored pattern, so /help silently fell through to the RAG path in
    # exactly the scope this app installs to by default.
    monkeypatch.setattr(agent_module, "agent_settings", AgentSettings())

    async def unexpected_answer(_request):
        raise AssertionError("/help must not reach the Agent Gateway.")

    install_gateway(monkeypatch, answer=unexpected_answer)
    ctx = FakeContext(scope)
    ctx.activity = mention_activity("/help", scope)

    await agent_module._handle_message(ctx)

    assert len(ctx.sent) == 1
    assert "目前模式" in ctx.sent[0]


@pytest.mark.asyncio
async def test_help_still_works_in_personal_chat(monkeypatch) -> None:
    monkeypatch.setattr(agent_module, "agent_settings", AgentSettings())

    async def unexpected_answer(_request):
        raise AssertionError("/help must not reach the Agent Gateway.")

    install_gateway(monkeypatch, answer=unexpected_answer)
    ctx = FakeContext("personal")
    ctx.activity = MessageActivity.model_validate(
        {
            "type": "message",
            "id": "activity-1",
            "channelId": "msteams",
            "from": {"id": "user-1"},
            "recipient": {"id": "bot-1"},
            "conversation": {"id": "conversation-1", "conversationType": "personal"},
            "text": "/help",
        }
    )

    await agent_module._handle_message(ctx)

    assert len(ctx.sent) == 1
    assert "目前模式" in ctx.sent[0]
