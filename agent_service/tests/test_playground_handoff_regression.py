"""Regression tests for the Playground handoff + ticket conversation (Aug 2026).

These tests simulate agentic router/extractor decisions with fakes while exercising
the real LangGraph workflow wiring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import test_workflow as tw

from agent_service.contracts import FaqEntry, KnowledgeResult, Ticket
from agent_service.extractor import HUMAN_ESCALATION_ISSUE_DESCRIPTION
from agent_service.faq import FaqRepository, FaqService
from agent_service.handoff import HandoffStatus, InMemoryHandoffRepository
from agent_service.handoff_flow import HandoffAction, HandoffRouteDecision
from agent_service.ticket_dedupe import InMemoryTicketRequestDedupeRepository

SAP_ISSUE = "SAP Crystal Reports 授權到期無法開啟"
PUBLIC_PHONE_ISSUE = "公發手機無法解鎖"


@pytest.mark.asyncio
async def test_handoff_router_receives_conversation_context(tmp_path: Path) -> None:
    captured: list[str] = []

    class CapturingModel:
        def with_structured_output(self, _schema):
            class Handle:
                async def ainvoke(self, messages):
                    captured.append(messages[-1].content)
                    return HandoffRouteDecision(action="CONTACT_HUMAN")

            return Handle()

    from agent_service.handoff_flow import AgenticHandoffRouter

    router = AgenticHandoffRouter(CapturingModel())
    action = await router.decide(
        message="我要找真人客服",
        case_status="SUMMARY_REVIEW",
        case_summary=f"問題：{SAP_ISSUE}",
        conversation_turns=[
            f"user: {SAP_ISSUE}",
            "assistant: handoff offer",
        ],
    )

    assert action is HandoffAction.CONTACT_HUMAN
    assert "Recent conversation" in captured[0]
    assert SAP_ISSUE in captured[0]


@pytest.mark.asyncio
async def test_demo_mode_create_ticket_uses_case_issue_not_full_summary(
    tmp_path: Path,
) -> None:
    ticket_service = tw.FakeTicketService()
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description=SAP_ISSUE)]],
        ticket_service=ticket_service,
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
        handoff_router=tw.FakeHandoffRouter(
            [
                HandoffAction.CONTACT_HUMAN,
                HandoffAction.CREATE_TICKET,
            ]
        ),
        ticket_item_selector=tw.FakeTicketItemSelector("item-1"),
    )

    offered = await workflow.respond(tw.make_request(SAP_ISSUE))
    demo = await workflow.respond(tw.make_request("我要找真人客服"))
    created = await workflow.respond(tw.make_request("建立派工單"))

    assert SAP_ISSUE in offered.answer
    assert "真人客服模式" in demo.answer
    assert created.issueResults[0].resultType == "TICKET_CREATED"
    assert ticket_service.created[0][0].title == SAP_ISSUE
    assert "使用者需求：" not in ticket_service.created[0][0].title


@pytest.mark.asyncio
async def test_summary_review_create_ticket_from_handoff_not_catalog_prompt(
    tmp_path: Path,
) -> None:
    ticket_service = tw.FakeTicketService()
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description=PUBLIC_PHONE_ISSUE)]],
        ticket_service=ticket_service,
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
        handoff_router=tw.FakeHandoffRouter([HandoffAction.CREATE_TICKET]),
        ticket_item_selector=tw.FakeTicketItemSelector("item-1"),
    )

    await workflow.respond(tw.make_request(PUBLIC_PHONE_ISSUE))
    created = await workflow.respond(tw.make_request("請協助建立派工單"))

    assert created.issueResults[0].resultType == "TICKET_CREATED"
    assert "MOCK-" in created.answer or created.issueResults[0].ticketId
    assert "目前無法從可用派工單類別判定" not in created.answer
    assert ticket_service.created[0][0].title == PUBLIC_PHONE_ISSUE


@pytest.mark.asyncio
async def test_handoff_create_ticket_falls_back_when_selector_is_uncertain(
    tmp_path: Path,
) -> None:
    from agent_service.ticket import TicketItem

    class CatalogTicketService(tw.FakeTicketService):
        def __init__(self) -> None:
            super().__init__()
            self.items = [
                TicketItem(id="item-system-function", name="系統功能異常", level=3),
            ]

    ticket_service = CatalogTicketService()
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description=SAP_ISSUE)]],
        ticket_service=ticket_service,
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
        handoff_router=tw.FakeHandoffRouter([HandoffAction.CREATE_TICKET]),
        ticket_item_selector=tw.FakeTicketItemSelector(
            item_id=None,
            reason="needs_clarification",
        ),
    )

    await workflow.respond(tw.make_request(SAP_ISSUE))
    created = await workflow.respond(tw.make_request("建立工單"))

    assert created.issueResults[0].resultType == "TICKET_CREATED"
    assert "目前無法從可用派工單類別判定" not in created.answer
    assert ticket_service.created[0][0].title == SAP_ISSUE
    assert ticket_service.created[0][0].ticketItemId == "item-system-function"


@pytest.mark.asyncio
async def test_human_escalation_after_ticket_query_is_not_rejected_as_non_it(
    tmp_path: Path,
) -> None:
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID"),
        responses={
            SAP_ISSUE: KnowledgeResult(found=False, answer="", backend="HYBRID"),
        },
    )
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[
            [tw.issue(description=SAP_ISSUE)],
            [tw.issue(description="使用者要求聯絡線上客服", route="KNOWLEDGE")],
        ],
        knowledge=knowledge,
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
        handoff_router=tw.FakeHandoffRouter([HandoffAction.NEW_ISSUE]),
    )

    await workflow.respond(tw.make_request(SAP_ISSUE))
    await workflow.respond(tw.make_request("建立派工單"))
    await workflow.respond(tw.make_request("是"))
    response = await workflow.respond(tw.make_request("我要找真人客服"))

    assert "不屬於公司 IT 支援範圍" not in response.answer
    assert "建立派工單" in response.answer or "聯絡線上客服" in response.answer


@pytest.mark.asyncio
async def test_playground_conversation_core_scenarios(tmp_path: Path) -> None:
    """Walk through the main Playground script with agentic fakes."""
    ticket_service = tw.FakeTicketService()
    handoff_repo = InMemoryHandoffRepository(clock=lambda: datetime.now(timezone.utc))
    handoff_router = tw.FakeHandoffRouter(
        [
            HandoffAction.CONTACT_HUMAN,
            HandoffAction.UNKNOWN,
            HandoffAction.CLOSE,
            HandoffAction.CREATE_TICKET,
            HandoffAction.NEW_ISSUE,
            HandoffAction.CREATE_TICKET,
        ]
    )
    vpn_need_more = tw.issue(
        description="VPN 密碼鎖住怎麼辦",
        readiness="NEED_MORE_INFO",
        missingInfo=["請問是行動裝置還是公司配發設備？"],
    )
    vpn_answer = KnowledgeResult(
        found=True,
        answer="等待 30 分鐘後自動解鎖。",
        backend="HYBRID",
    )
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID")
    )
    knowledge.responses["VPN 密碼鎖住怎麼辦"] = vpn_answer
    knowledge.responses["VPN 帳號密碼被鎖住，需要解鎖或重設"] = vpn_answer

    issues_sequence = [
        [tw.issue(description=SAP_ISSUE)],
        [tw.issue(description=SAP_ISSUE)],
        [
            tw.issue(
                description="VPN 帳號密碼被鎖住，需要解鎖或重設",
                readiness="READY",
            )
        ],
        [tw.issue(description=PUBLIC_PHONE_ISSUE)],
    ]
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=issues_sequence,
        knowledge=knowledge,
        ticket_service=ticket_service,
        handoff_repository=handoff_repo,
        handoff_router=handoff_router,
        ticket_query_router=tw.FakeTicketQueryRouter(
            ticket_queries={"我現在有哪些工單"}
        ),
        ticket_item_selector=tw.FakeTicketItemSelector("item-1"),
        extractor_by_message={
            "VPN 密碼鎖住怎麼辦": [vpn_need_more],
        },
    )

    sap_offer = await workflow.respond(tw.make_request(SAP_ISSUE))
    assert SAP_ISSUE in sap_offer.answer
    assert "建立派工單" in sap_offer.answer

    demo = await workflow.respond(tw.make_request("我要找真人客服"))
    assert "真人客服模式" in demo.answer

    saved = await workflow.respond(tw.make_request("132"))
    assert "已加入人工客服案件" in saved.answer

    closed = await workflow.respond(tw.make_request("/close"))
    assert "已結束" in closed.answer

    sap_again = await workflow.respond(tw.make_request(SAP_ISSUE))
    assert SAP_ISSUE in sap_again.answer

    ticket = await workflow.respond(tw.make_request("建立派工單"))
    assert ticket.issueResults[0].resultType == "TICKET_CREATED"

    listed = await workflow.respond(tw.make_request("我現在有哪些工單"))
    assert "派工單" in listed.answer

    escalation = await workflow.respond(tw.make_request("我要找真人客服"))
    assert "不屬於公司 IT 支援範圍" not in escalation.answer

    vpn = await workflow.respond(tw.make_request("VPN 密碼鎖住怎麼辦"))
    assert vpn.issueResults[0].resultType == "NEED_MORE_INFO"

    vpn_answered = await workflow.respond(tw.make_request("設備"))
    assert "30 分鐘" in vpn_answered.answer

    phone_offer = await workflow.respond(tw.make_request(PUBLIC_PHONE_ISSUE))
    assert PUBLIC_PHONE_ISSUE in phone_offer.answer

    phone_ticket = await workflow.respond(tw.make_request("請協助建立派工單"))
    assert phone_ticket.issueResults[0].resultType == "TICKET_CREATED"
    assert "目前無法從可用派工單類別判定" not in phone_ticket.answer


@pytest.mark.asyncio
async def test_ticket_query_supersedes_handoff_review_and_lists_tickets(
    tmp_path: Path,
) -> None:
    ticket_service = tw.FakeTicketService()
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description=SAP_ISSUE)]],
        ticket_service=ticket_service,
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
        handoff_router=tw.FakeHandoffRouter([HandoffAction.CREATE_TICKET]),
        ticket_query_router=tw.FakeTicketQueryRouter(
            ticket_queries={"確認我的工單", "我的工單", "查詢我的工單"}
        ),
        ticket_item_selector=tw.FakeTicketItemSelector("item-1"),
    )

    await workflow.respond(tw.make_request(SAP_ISSUE))
    await workflow.respond(tw.make_request("開工單"))

    confirm_list = await workflow.respond(tw.make_request("確認我的工單"))
    assert confirm_list.issueResults[0].resultType == "TICKET_FOUND"
    assert "派工單" in confirm_list.answer
    assert "目前無法從企業知識庫找到可確認的答案" not in confirm_list.answer

    listed = await workflow.respond(tw.make_request("我的工單"))
    assert listed.issueResults[0].resultType == "TICKET_FOUND"

    listed_again = await workflow.respond(tw.make_request("查詢我的工單"))
    assert listed_again.issueResults[0].resultType == "TICKET_FOUND"


@pytest.mark.asyncio
async def test_standalone_human_escalation_offers_handoff_without_knowledge_lookup(
    tmp_path: Path,
) -> None:
    knowledge = tw.FakeKnowledgeService(
        responses={
            HUMAN_ESCALATION_ISSUE_DESCRIPTION: KnowledgeResult(
                found=True,
                answer="XQ 客服電話：0800-006-098",
                backend="HYBRID",
            ),
        }
    )
    workflow, extractor_model, knowledge_service, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description="不應被使用")]],
        knowledge=knowledge,
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
    )

    response = await workflow.respond(tw.make_request("聯絡線上客服"))

    assert extractor_model.calls == 0
    assert knowledge_service.calls == []
    assert "0800-006-098" not in response.answer
    assert "XQ" not in response.answer
    assert "建立派工單" in response.answer
    assert "聯絡線上客服" in response.answer


@pytest.mark.asyncio
async def test_assistant_scope_question_supersedes_handoff_review(
    tmp_path: Path,
) -> None:
    workflow, extractor_model, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description="大州系統無法顯示")]],
        knowledge=tw.FakeKnowledgeService(
            default=KnowledgeResult(found=False, answer="", backend="HYBRID"),
        ),
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
    )

    await workflow.respond(tw.make_request("大洲無法顯示"))
    calls_after_handoff = extractor_model.calls
    response = await workflow.respond(tw.make_request("你能回答什麼問題"))

    assert extractor_model.calls == calls_after_handoff
    assert "我目前專門協助處理公司 IT 問題" in response.answer
    assert "建立派工單" not in response.answer
    assert "目前無法從企業知識庫找到可確認的答案" not in response.answer


@pytest.mark.asyncio
async def test_assistant_scope_question_does_not_trigger_handoff(tmp_path: Path) -> None:
    workflow, extractor_model, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description="不應被使用")]],
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
    )

    response = await workflow.respond(tw.make_request("你能回瘩什麼問題"))

    assert extractor_model.calls == 0
    assert "目前無法從企業知識庫找到可確認的答案" not in response.answer
    assert "建立派工單" not in response.answer
    assert "我目前專門協助處理公司 IT 問題" in response.answer


@pytest.mark.asyncio
async def test_new_issue_after_sap_handoff_clears_case_and_answers_vpn(
    tmp_path: Path,
) -> None:
    """Scenario 1: unrelated VPN question supersedes pending SAP handoff."""
    vpn_issue = tw.issue(
        description="VPN 密碼鎖住怎麼辦",
        readiness="NEED_MORE_INFO",
        missingInfo=["請問是行動裝置還是公司配發設備？"],
    )
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID"),
        responses={
            vpn_issue.description: KnowledgeResult(
                found=True,
                answer="等待 30 分鐘後自動解鎖。",
                backend="HYBRID",
            ),
        },
    )
    handoff_repo = InMemoryHandoffRepository(clock=lambda: datetime.now(timezone.utc))
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description=SAP_ISSUE)]],
        knowledge=knowledge,
        handoff_repository=handoff_repo,
        handoff_router=tw.FakeHandoffRouter([HandoffAction.NEW_ISSUE]),
        extractor_by_message={vpn_issue.description: [vpn_issue]},
    )

    await workflow.respond(tw.make_request(SAP_ISSUE))
    active = await handoff_repo.get_active_case("tenant-1", "conv-1", "user-1")
    assert active is not None

    vpn = await workflow.respond(tw.make_request(vpn_issue.description))
    stored = await handoff_repo.get_case(active.caseId)

    assert stored is not None and stored.status == HandoffStatus.CANCELLED
    assert SAP_ISSUE not in vpn.answer
    assert vpn.issueResults[0].resultType == "NEED_MORE_INFO"
    assert knowledge.calls == [SAP_ISSUE]


@pytest.mark.asyncio
async def test_handoff_create_ticket_is_idempotent_by_request_id(tmp_path: Path) -> None:
    """Scenario 2: replaying the same requestId must not create another ticket."""
    ticket_service = tw.FakeTicketService()
    dedupe = InMemoryTicketRequestDedupeRepository()
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description=PUBLIC_PHONE_ISSUE)]],
        ticket_service=ticket_service,
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
        handoff_router=tw.FakeHandoffRouter([HandoffAction.CREATE_TICKET]),
        ticket_item_selector=tw.FakeTicketItemSelector("item-1"),
        ticket_request_dedupe=dedupe,
    )

    await workflow.respond(tw.make_request(PUBLIC_PHONE_ISSUE))
    first = await workflow.respond(
        tw.make_request("請協助建立派工單", request_id="ticket-req-1")
    )
    replay = await workflow.respond(
        tw.make_request("請協助建立派工單", request_id="ticket-req-1")
    )

    assert first.issueResults[0].resultType == "TICKET_CREATED"
    assert replay.issueResults[0].resultType == "TICKET_CREATED"
    assert first.issueResults[0].ticketId == replay.issueResults[0].ticketId
    assert len(ticket_service.created) == 1


@pytest.mark.asyncio
async def test_contact_human_typo_uses_pending_case_via_agentic_router(
    tmp_path: Path,
) -> None:
    """Scenario 3: typo escalation is resolved by injected semantic handoff routing."""
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description=SAP_ISSUE)]],
        handoff_repository=InMemoryHandoffRepository(
            clock=lambda: datetime.now(timezone.utc)
        ),
        handoff_router=tw.FakeHandoffRouter([HandoffAction.CONTACT_HUMAN]),
    )

    await workflow.respond(tw.make_request(SAP_ISSUE))
    response = await workflow.respond(tw.make_request("流落線上客服"))

    assert "真人客服模式" in response.answer


@pytest.mark.asyncio
async def test_agentic_ticket_query_beats_faq_and_knowledge(tmp_path: Path) -> None:
    """Scenario 4: structured ticket-query intent routes before FAQ/knowledge."""
    faq = FaqService(
        FaqRepository(
            [
                FaqEntry(
                    id="1",
                    faqKey="TICKET_FAQ",
                    enabled=True,
                    answer="FAQ must not win",
                )
            ]
        )
    )
    ticket_service = tw.FakeTicketService()
    ticket_service._by_requester["user-1"] = [
        Ticket(
            id="TCK-1",
            title="VPN 問題",
            status="OPEN",
            url="https://tickets/TCK-1",
        )
    ]
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="Knowledge must not win", backend="HYBRID")
    )
    workflow, extractor_model, knowledge_service, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(route="FAQ", faqKey="TICKET_FAQ")]],
        faq_service=faq,
        knowledge=knowledge,
        ticket_service=ticket_service,
        ticket_query_router=tw.FakeTicketQueryRouter(
            ticket_queries={"我的派工單", "我有哪些工單"}
        ),
    )

    for text in ("我的派工單", "我有哪些工單"):
        response = await workflow.respond(tw.make_request(text))
        assert response.issueResults[0].resultType == "TICKET_FOUND"
        assert "FAQ must not win" not in response.answer
        assert "Knowledge must not win" not in response.answer

    assert extractor_model.calls == 0
    assert knowledge_service.calls == []


@pytest.mark.asyncio
async def test_successful_knowledge_answer_clears_pending_handoff_offer(
    tmp_path: Path,
) -> None:
    """Scenario 5: a knowledge hit closes a stale handoff offer for the next turn."""
    vpn_issue = tw.issue(description="VPN 密碼鎖住怎麼辦", readiness="READY")
    knowledge = tw.FakeKnowledgeService(
        responses={
            SAP_ISSUE: KnowledgeResult(found=False, answer="", backend="HYBRID"),
            vpn_issue.description: KnowledgeResult(
                found=True,
                answer="等待 30 分鐘後自動解鎖。",
                backend="HYBRID",
            ),
        }
    )
    handoff_repo = InMemoryHandoffRepository(clock=lambda: datetime.now(timezone.utc))
    workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[tw.issue(description=SAP_ISSUE)], [vpn_issue]],
        knowledge=knowledge,
        handoff_repository=handoff_repo,
        handoff_router=tw.FakeHandoffRouter([HandoffAction.NEW_ISSUE]),
    )

    await workflow.respond(tw.make_request(SAP_ISSUE))
    answered = await workflow.respond(tw.make_request(vpn_issue.description))
    follow_up = await workflow.respond(tw.make_request("謝謝"))

    assert "30 分鐘" in answered.answer
    assert await handoff_repo.get_active_case("tenant-1", "conv-1", "user-1") is None
    assert "建立派工單" not in follow_up.answer
    assert SAP_ISSUE not in follow_up.answer
