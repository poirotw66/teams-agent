import pytest

from agent_service.supervisor import ConversationSupervisor, ConversationSupervisorDecision


@pytest.mark.asyncio
async def test_supervisor_classifies_unknown_chitchat_via_model() -> None:
    class CapturingModel:
        schemas: list = []

        def with_structured_output(self, schema):
            CapturingModel.schemas.append(schema)

            class Handle:
                async def ainvoke(self, _messages):
                    return ConversationSupervisorDecision(
                        intent="NON_IT",
                        confidence=0.9,
                    )

            return Handle()

    decision = await ConversationSupervisor(CapturingModel()).decide(message="午餐呢")
    assert decision.intent == "NON_IT"
    assert CapturingModel.schemas == [ConversationSupervisorDecision]


@pytest.mark.asyncio
async def test_supervisor_without_model_returns_unknown() -> None:
    decision = await ConversationSupervisor(None).decide(message="VPN 無法登入")
    assert decision.intent == "UNKNOWN"
