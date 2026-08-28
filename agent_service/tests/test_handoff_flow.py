from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from agent_service.handoff_flow import (
    CLOSE_FORBIDDEN_MESSAGE,
    DEMO_CLOSED_MESSAGE,
    DEMO_MESSAGE_SAVED,
    HandoffAction,
    HandoffRouter,
    RoutingTarget,
    deterministic_summary,
    generate_summary_with_fallback,
    offer_message,
    parse_handoff_action,
    routing_target_for_status,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("建立工單", HandoffAction.CREATE_TICKET),
        ("  聯絡線上客服。 ", HandoffAction.CONTACT_HUMAN),
        ("真人客服", HandoffAction.CONTACT_HUMAN),
        ("修改摘要", HandoffAction.SUPPLEMENT),
        ("取消", HandoffAction.CANCEL),
        ("/close", HandoffAction.CLOSE),
        ("不要建立工單", HandoffAction.NONE),
        ("我的訊息包含 /close 但不是指令", HandoffAction.NONE),
    ],
)
def test_parse_handoff_action_is_deterministic(text, expected) -> None:
    assert parse_handoff_action(text) is expected


def test_deterministic_summary_has_every_required_section() -> None:
    fixed = datetime(2026, 8, 28, tzinfo=timezone.utc)
    summary = deterministic_summary(
        current_message="VPN 無法登入，請協助",
        issue_descriptions=["VPN 無法登入"],
        conversation_highlights=["錯誤碼 691"],
        attempted_solutions=["已重設密碼"],
        now=fixed,
    )

    assert summary.issue == "VPN 無法登入"
    assert summary.generated_at == fixed
    rendered = summary.render()
    assert "使用者需求：VPN 無法登入，請協助" in rendered
    assert "對話重點：錯誤碼 691" in rendered
    assert "已嘗試方式：已重設密碼" in rendered
    assert "尚未解決原因：" in rendered
    assert "期望結果：" in rendered


def test_deterministic_summary_redacts_common_credentials() -> None:
    summary = deterministic_summary(
        current_message="VPN 密碼：SuperSecret123 API_KEY=abc-123 Bearer ey.secret.token",
    )

    rendered = summary.render()
    assert "SuperSecret123" not in rendered
    assert "abc-123" not in rendered
    assert "ey.secret.token" not in rendered
    assert "[REDACTED]" in rendered


@pytest.mark.asyncio
async def test_summary_generator_failure_uses_deterministic_fallback() -> None:
    async def unavailable(**_kwargs):
        raise TimeoutError("model unavailable")

    summary = await generate_summary_with_fallback(
        unavailable,
        current_message="Outlook 無法寄信",
        issue_descriptions=["Outlook 寄信失敗"],
    )

    assert summary.issue == "Outlook 寄信失敗"
    assert "Outlook 無法寄信" in offer_message(summary)
    assert "建立工單" in offer_message(summary)
    assert "聯絡線上客服" in offer_message(summary)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, RoutingTarget.AI_AGENT),
        ("OFFERED", RoutingTarget.AI_AGENT),
        ("SUMMARY_REVIEW", RoutingTarget.AI_AGENT),
        ("DEMO_ACTIVE", RoutingTarget.HUMAN_DEMO),
        ("CLOSED", RoutingTarget.AI_AGENT),
        ("ROUTED_TO_TICKET", RoutingTarget.AI_AGENT),
    ],
)
def test_routing_target_is_derived_from_case_status(status, expected) -> None:
    assert routing_target_for_status(status) is expected


@dataclass
class FakeCase:
    status: str
    requesterId: str


class FakeRepository:
    def __init__(self, case):
        self.case = case
        self.lookups = []

    async def get_active_case(self, tenant_id, conversation_id, requester_id):
        self.lookups.append((tenant_id, conversation_id, requester_id))
        return self.case


@pytest.mark.asyncio
async def test_demo_active_message_bypasses_ai_and_must_be_saved() -> None:
    router = HandoffRouter(FakeRepository(FakeCase("DEMO_ACTIVE", "user-1")))

    decision = await router.decide(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        requester_id="user-1",
        message="補充：錯誤碼是 691",
    )

    assert decision.handled is True
    assert decision.bypass_ai is True
    assert decision.should_save_message is True
    assert decision.answer == DEMO_MESSAGE_SAVED
    assert "已送達客服" not in decision.answer
    assert "客服已接手" not in decision.answer


@pytest.mark.asyncio
async def test_requester_close_is_consumed_without_ai() -> None:
    router = HandoffRouter(FakeRepository(FakeCase("DEMO_ACTIVE", "user-1")))

    decision = await router.decide(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        requester_id="user-1",
        message="/close",
    )

    assert decision.should_close is True
    assert decision.bypass_ai is True
    assert decision.answer == DEMO_CLOSED_MESSAGE


@pytest.mark.asyncio
async def test_non_requester_cannot_close_case() -> None:
    router = HandoffRouter(FakeRepository(FakeCase("DEMO_ACTIVE", "owner")))

    decision = await router.decide(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        requester_id="intruder",
        message="/close",
    )

    assert decision.should_close is False
    assert decision.answer == CLOSE_FORBIDDEN_MESSAGE
    assert decision.bypass_ai is True


@pytest.mark.asyncio
async def test_no_active_case_continues_to_ai() -> None:
    router = HandoffRouter(FakeRepository(None))

    decision = await router.decide(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        requester_id="user-1",
        message="VPN 無法登入",
    )

    assert decision.handled is False
    assert decision.bypass_ai is False
    assert decision.routing_target is RoutingTarget.AI_AGENT
