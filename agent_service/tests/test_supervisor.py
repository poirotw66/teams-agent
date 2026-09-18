from typing import ClassVar

import pytest

from agent_service.supervisor import ConversationSupervisor, ConversationSupervisorDecision


@pytest.mark.asyncio
async def test_supervisor_classifies_unknown_chitchat_via_model() -> None:
    class CapturingModel:
        schemas: ClassVar[list[type]] = []

        def with_structured_output(self, schema):
            CapturingModel.schemas.append(schema)

            class Handle:
                async def ainvoke(self, _messages):
                    return ConversationSupervisorDecision(
                        intent="NON_IT",
                        confidence=0.9,
                    )

            return Handle()

    decision = await ConversationSupervisor(CapturingModel()).decide(
        message="午餐呢",
        recent_turns=["user: VPN 無法登入"],
    )
    assert decision.intent == "NON_IT"
    assert CapturingModel.schemas == [ConversationSupervisorDecision]


@pytest.mark.asyncio
async def test_supervisor_without_model_routes_standalone_turn_to_extractor() -> None:
    decision = await ConversationSupervisor(None).decide(message="VPN 無法登入")
    assert decision.intent == "IT_SUPPORT"


@pytest.mark.asyncio
async def test_supervisor_does_not_model_route_standalone_it_turn() -> None:
    class FailingModel:
        def with_structured_output(self, _schema):
            raise AssertionError("ordinary standalone turns must bypass the supervisor model")

    decision = await ConversationSupervisor(FailingModel()).decide(
        message="你好，VPN 連不上",
    )

    assert decision.intent == "IT_SUPPORT"
    assert decision.confidence == 1.0


@pytest.mark.asyncio
async def test_supervisor_handles_pure_greeting_deterministically() -> None:
    decision = await ConversationSupervisor(None).decide(message="你好！")

    assert decision.intent == "GREETING"
    assert decision.confidence == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["你好呀", "你好牙", "謝謝喔", "哈囉啊"])
async def test_supervisor_handles_greeting_particles_deterministically(
    message: str,
) -> None:
    decision = await ConversationSupervisor(None).decide(message=message)

    assert decision.intent == "GREETING"
    assert decision.confidence == 1.0


@pytest.mark.asyncio
async def test_supervisor_remaps_short_social_non_it_to_greeting() -> None:
    class NonItModel:
        def with_structured_output(self, _schema):
            class Handle:
                async def ainvoke(self, _messages):
                    return ConversationSupervisorDecision(
                        intent="NON_IT",
                        confidence=0.94,
                    )

            return Handle()

    decision = await ConversationSupervisor(NonItModel()).decide(
        message="嗨嗨～",
        recent_turns=["user: VPN 無法登入"],
    )

    assert decision.intent == "GREETING"
    assert decision.confidence == 0.94


@pytest.mark.asyncio
async def test_supervisor_keeps_clear_non_it_for_food_chitchat() -> None:
    class NonItModel:
        def with_structured_output(self, _schema):
            class Handle:
                async def ainvoke(self, _messages):
                    return ConversationSupervisorDecision(
                        intent="NON_IT",
                        confidence=0.9,
                    )

            return Handle()

    decision = await ConversationSupervisor(NonItModel()).decide(
        message="午餐呢",
        recent_turns=["user: VPN 無法登入"],
    )

    assert decision.intent == "NON_IT"


@pytest.mark.asyncio
async def test_supervisor_rejects_unsubstantiated_ticket_creation() -> None:
    class TicketModel:
        def with_structured_output(self, _schema):
            class Handle:
                async def ainvoke(self, _messages):
                    return ConversationSupervisorDecision(
                        intent="TICKET_CREATE",
                        requestedAction="CREATE_TICKET",
                        confidence=0.99,
                    )

            return Handle()

    decision = await ConversationSupervisor(TicketModel()).decide(
        message="這問題會產生 ticket 嗎",
        pending_clarification=True,
        recent_turns=["user: VPN 無法登入"],
    )

    assert decision.intent == "IT_SUPPORT"
    assert decision.requestedAction == "NONE"
