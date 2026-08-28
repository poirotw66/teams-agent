import pytest

from agent_service.supervisor import ConversationSupervisor


@pytest.mark.asyncio
async def test_supervisor_detects_scope_question() -> None:
    decision = ConversationSupervisor.deterministic("你能回答什麼問題")
    assert decision.intent == "ASSISTANT_META"


@pytest.mark.asyncio
async def test_supervisor_detects_human_escalation() -> None:
    decision = ConversationSupervisor.deterministic("聯絡線上客服")
    assert decision.intent == "HUMAN_ESCALATION"


@pytest.mark.asyncio
async def test_supervisor_detects_clarification_unknown() -> None:
    decision = ConversationSupervisor.deterministic("不知道", pending_clarification=True)
    assert decision.clarificationDisposition == "UNKNOWN"


@pytest.mark.asyncio
async def test_supervisor_detects_clarification_abandon() -> None:
    decision = ConversationSupervisor.deterministic("算了不問了", pending_clarification=True)
    assert decision.topicRelation == "ABANDON"
    assert decision.clarificationDisposition == "ABANDON"
