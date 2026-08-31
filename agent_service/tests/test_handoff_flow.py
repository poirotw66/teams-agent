from datetime import datetime, timezone

import pytest

from agent_service.handoff_flow import (
    AgenticHandoffRouter,
    HandoffAction,
    HandoffRouteDecision,
    RoutingTarget,
    deterministic_summary,
    generate_summary_with_fallback,
    offer_message,
    routing_target_for_status,
    supplement_summary_deterministic_fallback,
    validate_handoff_action,
)


class FakeStructuredModel:
    def __init__(self, decision: HandoffRouteDecision | Exception) -> None:
        self.decision = decision
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        outer = self

        class Handle:
            async def ainvoke(self, _messages):
                if isinstance(outer.decision, Exception):
                    raise outer.decision
                return outer.decision

        return Handle()


@pytest.mark.asyncio
async def test_agentic_router_revise_issue_in_awaiting_supplement() -> None:
    model = FakeStructuredModel(HandoffRouteDecision(action="REVISE_ISSUE"))
    router = AgenticHandoffRouter(model)

    action = await router.decide(
        message="其實不是解鎖，是不能點",
        case_status="AWAITING_SUPPLEMENT",
        case_summary="問題：大洲系統無法解鎖",
    )

    assert action is HandoffAction.REVISE_ISSUE


def test_validate_handoff_action_rejects_supplement_outside_awaiting_phase() -> None:
    assert (
        validate_handoff_action("SUMMARY_REVIEW", HandoffAction.SUPPLEMENT)
        is HandoffAction.UNKNOWN
    )
    assert (
        validate_handoff_action("AWAITING_SUPPLEMENT", HandoffAction.SUPPLEMENT)
        is HandoffAction.SUPPLEMENT
    )


def test_supplement_fallback_preserves_issue_and_marks_pending_confirmation() -> None:
    draft = supplement_summary_deterministic_fallback(
        issue="大洲系統無法解鎖",
        user_need="需要解鎖大洲",
        conversation_highlights=["已重開機"],
        attempted_solutions=[],
        supplement_message="錯誤碼 E-42",
    )

    assert draft.issue == "大洲系統無法解鎖"
    assert draft.user_need == "需要解鎖大洲"
    assert draft.conversation_highlights[-1] == "待確認補充：錯誤碼 E-42"


@pytest.mark.asyncio
async def test_agentic_router_uses_structured_semantic_decision() -> None:
    model = FakeStructuredModel(HandoffRouteDecision(action="NEW_ISSUE"))
    router = AgenticHandoffRouter(model)

    action = await router.decide(
        message="VPN 密碼鎖住怎麼辦",
        case_status="SUMMARY_REVIEW",
        case_summary="問題：SAP Crystal Reports 授權到期無法開啟",
    )

    assert action is HandoffAction.NEW_ISSUE
    assert model.schemas == [HandoffRouteDecision]


@pytest.mark.asyncio
async def test_agentic_router_failure_degrades_without_keyword_rules() -> None:
    router = AgenticHandoffRouter(FakeStructuredModel(TimeoutError("offline")))

    review_action = await router.decide(
        message="任何文字",
        case_status="SUMMARY_REVIEW",
        case_summary="案件摘要",
    )
    demo_action = await router.decide(
        message="任何文字",
        case_status="DEMO_ACTIVE",
        case_summary="案件摘要",
    )

    assert review_action is HandoffAction.UNKNOWN
    assert demo_action is HandoffAction.HUMAN_MESSAGE


@pytest.mark.asyncio
async def test_agentic_router_without_model_preserves_summary_review_case() -> None:
    action = await AgenticHandoffRouter(None).decide(
        message="maybe later",
        case_status="SUMMARY_REVIEW",
        case_summary="案件摘要",
        conversation_turns=["user: SAP issue", "assistant: offer"],
    )

    assert action is HandoffAction.UNKNOWN


@pytest.mark.asyncio
async def test_agentic_router_summary_review_uses_model_without_keyword_rules() -> None:
    model = FakeStructuredModel(HandoffRouteDecision(action="CREATE_TICKET"))
    router = AgenticHandoffRouter(model)

    action = await router.decide(
        message="建立派工單",
        case_status="SUMMARY_REVIEW",
        case_summary="問題：SAP Crystal Reports 授權到期無法開啟",
    )

    assert action is HandoffAction.CREATE_TICKET
    assert model.schemas == [HandoffRouteDecision]


@pytest.mark.asyncio
async def test_agentic_router_close_command_in_demo_is_protocol_not_keywords() -> None:
    action = await AgenticHandoffRouter(None).decide(
        message="/close",
        case_status="DEMO_ACTIVE",
        case_summary="案件摘要",
    )

    assert action is HandoffAction.CLOSE


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
    assert "建立派工單" in offer_message(summary)
    assert "聯絡線上客服" in offer_message(summary)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, RoutingTarget.AI_AGENT),
        ("OFFERED", RoutingTarget.AI_AGENT),
        ("SUMMARY_REVIEW", RoutingTarget.AI_AGENT),
        ("AWAITING_SUPPLEMENT", RoutingTarget.AI_AGENT),
        ("DEMO_ACTIVE", RoutingTarget.HUMAN_DEMO),
        ("CLOSED", RoutingTarget.AI_AGENT),
        ("ROUTED_TO_TICKET", RoutingTarget.AI_AGENT),
    ],
)
def test_routing_target_is_derived_from_case_status(status, expected) -> None:
    assert routing_target_for_status(status) is expected


