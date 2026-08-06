"""§19 POC 驗收標準 acceptance checklist — one test per checkable item.

Items 1, 2, 12, 22 are NOT unit-testable in this suite (live Teams
connectivity, an actual Cloud Run deployment, real Teams image rendering,
and a load/performance test respectively) — see
``docs/security-test-report.md`` for how those are verified instead
(manually / operationally / deferred).

Every other numbered item below (3,4,5,6,7,8,9,10,11,13,14,15,16,17,18,19,20)
gets its own test, named ``test_acceptance_<NN>_<slug>`` so the mapping
back to the spec is unambiguous. Item 21 (具備安全、錯誤與 Prompt Injection
測試) is what ``test_security.py`` and this file collectively ARE — it has
no separate test of its own here.

Tests reuse the ``test_workflow.py`` stub/fixture stack (imported as a
module) rather than duplicating it, and use ``fastapi.testclient.TestClient``
against ``create_app`` for the couple of items that are inherently
HTTP-layer concerns (item 3's trusted-identity plumbing at the wire level,
and item 20's ``/feedback`` endpoint).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import test_workflow as tw
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.contracts import KnowledgeResult, UserIdentity
from agent_service.graph import user_context_from_identity
from agent_service.settings import RagSettings

# --------------------------------------------------------------------------
# 3. 可取得可信任的使用者識別資訊
# --------------------------------------------------------------------------


def test_acceptance_03_trusted_user_identity_is_extracted_from_request() -> None:
    identity = UserIdentity(
        teamsUserId="teams-1",
        entraObjectId="entra-1",
        displayName="Alice Chen",
        email="alice@example.com",
        groups=["IT"],
    )

    context = user_context_from_identity(identity)

    assert context.entraObjectId == "entra-1"
    assert context.teamsUserId == "teams-1"
    assert context.displayName == "Alice Chen"
    assert context.email == "alice@example.com"
    assert context.groups == ["IT"]
    # Spec §11.4: this is exactly what gates trusted ticket creation.
    assert context.is_trusted_for_ticket is True


def test_acceptance_03_incomplete_identity_is_not_trusted_for_tickets() -> None:
    identity = UserIdentity(teamsUserId="teams-1")  # no displayName/email

    context = user_context_from_identity(identity)

    assert context.is_trusted_for_ticket is False


# --------------------------------------------------------------------------
# 4. 可載入最近對話上下文
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_04_loads_recent_conversation_context_across_turns(
    tmp_path: Path,
) -> None:
    first_issue = tw.issue(
        id=1,
        description="VPN 有問題",
        readiness="NEED_MORE_INFO",
        missingInfo=["使用的 VPN 應用程式名稱"],
    )
    second_issue = tw.issue(id=1, description="Cisco AnyConnect", readiness="READY")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請重新啟動用戶端。", backend="HYBRID")
    )
    workflow, extractor_model, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[[first_issue], [second_issue]], knowledge=knowledge
    )

    await workflow.respond(tw.make_request("VPN 有問題"))
    await workflow.respond(tw.make_request("Cisco AnyConnect"))

    # The second extraction call's prompt carried the first turn's history —
    # proof the recent conversation context was actually loaded and reused.
    assert extractor_model.calls == 2
    assert any("VPN 有問題" in text for text in extractor_model.human_messages)


# --------------------------------------------------------------------------
# 5. 可拆解最多三個 Issue
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_05_splits_up_to_three_issues_and_prioritizes_the_rest(
    tmp_path: Path,
) -> None:
    issues = [tw.issue(id=i, description=f"問題{i}") for i in range(1, 5)]
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="OK", backend="HYBRID")
    )
    workflow, *_ = tw.build_workflow(tmp_path, issues_sequence=[issues], knowledge=knowledge)

    response = await workflow.respond(tw.make_request("四個問題一次問"))

    assert len(response.issueResults) == 3
    assert "已先協助你處理最重要的" in response.answer


# --------------------------------------------------------------------------
# 6. 可判斷 IT 與非 IT 問題
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_06_classifies_it_versus_non_it_issues(tmp_path: Path) -> None:
    issues = [
        tw.issue(id=1, description="VPN 無法登入"),
        tw.issue(
            id=2, description="今天午餐吃什麼？", isIT=False, readiness="NOT_IT", route="NOT_IT"
        ),
    ]
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請重試登入。", backend="HYBRID")
    )
    workflow, *_ = tw.build_workflow(tmp_path, issues_sequence=[issues], knowledge=knowledge)

    response = await workflow.respond(tw.make_request("VPN 無法登入，另外今天午餐吃什麼？"))

    assert len(response.issueResults) == 1  # only the IT issue got processed
    assert response.issueResults[0].issueId == 1
    assert "午餐" in response.answer  # the non-IT issue still shows its own line
    assert "不在此 IT 助手的服務範圍" in response.answer


# --------------------------------------------------------------------------
# 7. FAQ 命中時回覆固定答案
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_07_faq_hit_returns_the_fixed_answer_verbatim(
    tmp_path: Path,
) -> None:
    from agent_service.contracts import FaqEntry
    from agent_service.faq import FaqRepository, FaqService

    entry = FaqEntry(id="1", faqKey="PW_RESET", enabled=True, answer="請至公司密碼管理入口重設密碼。")
    faq_service = FaqService(FaqRepository([entry]))
    it_issue = tw.issue(id=1, description="忘記密碼", route="FAQ", faqKey="PW_RESET")
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[[it_issue]], faq_service=faq_service
    )

    response = await workflow.respond(tw.make_request("忘記密碼怎麼辦"))

    assert response.issueResults[0].resultType == "FAQ_ANSWERED"
    assert response.issueResults[0].answer == entry.answer  # not rewritten


# --------------------------------------------------------------------------
# 8. 資訊不足時提出最多兩個必要問題
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_08_asks_at_most_two_followup_questions(tmp_path: Path) -> None:
    it_issue = tw.issue(
        id=1,
        description="VPN 問題",
        readiness="NEED_MORE_INFO",
        missingInfo=["使用的 VPN 應用程式名稱", "錯誤訊息或錯誤碼"],
    )
    workflow, *_ = tw.build_workflow(tmp_path, issues_sequence=[[it_issue]])

    response = await workflow.respond(tw.make_request("VPN 有問題"))

    result = response.issueResults[0]
    assert result.resultType == "NEED_MORE_INFO"
    assert len(result.questions) <= 2
    assert "1. 使用的 VPN 應用程式名稱" in response.answer
    assert "2. 錯誤訊息或錯誤碼" in response.answer


# --------------------------------------------------------------------------
# 9. 資訊完整時可執行 Hybrid RAG
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_09_ready_issue_executes_knowledge_search(tmp_path: Path) -> None:
    it_issue = tw.issue(id=1, description="VPN 無法連線", readiness="READY", route="KNOWLEDGE")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請重新安裝 VPN 用戶端。", backend="HYBRID")
    )
    workflow, *_ = tw.build_workflow(tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge)

    response = await workflow.respond(tw.make_request("VPN 無法連線"))

    assert knowledge.calls == ["VPN 無法連線"]
    assert response.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"


# --------------------------------------------------------------------------
# 10. 回答只根據知識內容
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_10_answer_grounded_only_in_retrieved_knowledge(
    tmp_path: Path,
) -> None:
    import test_knowledge as tk

    from agent_service.knowledge import HybridKnowledgeService
    from agent_service.retrieval import HybridIndex

    chunk = tk.vpn_chunk(content="VPN 密碼被鎖時，請聯繫資訊小幫手協助解鎖。")
    index = HybridIndex([chunk])
    service = HybridKnowledgeService(tk.make_settings(tmp_path), index, model=None)

    result = await service.search("VPN 密碼被鎖怎麼辦？", tk.make_user())

    assert result.found is True
    assert "VPN 密碼被鎖" in result.answer  # traceable straight to the source chunk
    assert result.sources[0].title == chunk.title


# --------------------------------------------------------------------------
# 11. 回覆包含來源文件
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_11_reply_includes_source_citations(tmp_path: Path) -> None:
    from agent_service.contracts import Citation

    it_issue = tw.issue(id=1, description="VPN 無法連線")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(
            found=True,
            answer="請重新安裝 VPN 用戶端。",
            sources=[Citation(title="VPN 疑難排解手冊", url="https://kb.example/vpn")],
            backend="HYBRID",
        )
    )
    workflow, *_ = tw.build_workflow(tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge)

    response = await workflow.respond(tw.make_request("VPN 無法連線"))

    assert response.citations
    assert response.citations[0].title == "VPN 疑難排解手冊"
    assert "來源" in response.answer
    assert "VPN 疑難排解手冊" in response.answer


# --------------------------------------------------------------------------
# 13. 無知識時不捏造
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_13_no_knowledge_does_not_fabricate_an_answer(
    tmp_path: Path,
) -> None:
    it_issue = tw.issue(id=1, description="不存在的系統問題")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID")
    )
    workflow, *_ = tw.build_workflow(tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge)

    response = await workflow.respond(tw.make_request("不存在的系統問題"))

    result = response.issueResults[0]
    assert result.resultType == "NO_KNOWLEDGE"
    assert result.answer == ""
    assert result.sources == []
    assert "查無相關資訊" in response.answer


# --------------------------------------------------------------------------
# 14. 未經確認不建立工單
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_14_ticket_not_created_without_confirmation(tmp_path: Path) -> None:
    it_issue = tw.issue(id=1, description="VPN 一直斷線", route="TICKET")
    ticket_service = tw.FakeTicketService()
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[[it_issue]], ticket_service=ticket_service
    )

    response = await workflow.respond(tw.make_request("可能要報修"))

    assert ticket_service.created == []
    assert response.issueResults[0].resultType != "TICKET_CREATED"


# --------------------------------------------------------------------------
# 15. 使用者確認後可呼叫 Ticket API
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_15_ticket_api_called_after_explicit_confirmation(
    tmp_path: Path,
) -> None:
    it_issue = tw.issue(id=1, description="VPN 一直斷線", route="TICKET")
    ticket_service = tw.FakeTicketService()
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[[it_issue]], ticket_service=ticket_service
    )

    response = await workflow.respond(tw.make_request("請幫我建立工單"))

    assert len(ticket_service.created) == 1
    assert response.issueResults[0].resultType == "TICKET_CREATED"


# --------------------------------------------------------------------------
# 16. 可查詢目前使用者自己的工單
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_16_queries_current_users_own_tickets(tmp_path: Path) -> None:
    from agent_service.contracts import Ticket

    it_issue = tw.issue(id=1, description="查詢我的工單", route="TICKET")
    ticket_service = tw.FakeTicketService()
    ticket_service._by_requester["user-1"] = [
        Ticket(id="TCK-1", title="VPN 問題", status="OPEN", url="https://tickets/TCK-1")
    ]
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[[it_issue]], ticket_service=ticket_service
    )

    response = await workflow.respond(
        tw.make_request("查詢我的工單", user=tw.trusted_user(entraObjectId="user-1"))
    )

    result = response.issueResults[0]
    assert result.resultType == "TICKET_FOUND"
    assert result.sources[0].title.startswith("VPN 問題")


# --------------------------------------------------------------------------
# 17. 可保存必要的 Conversation Context
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_17_conversation_context_is_saved(tmp_path: Path) -> None:
    it_issue = tw.issue(id=1, description="VPN 無法連線")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請重新安裝 VPN 用戶端。", backend="HYBRID")
    )
    workflow, _model, _knowledge, _ticket, conv_service, _settings = tw.build_workflow(
        tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge
    )
    request = tw.make_request("VPN 無法連線")

    state = await workflow.run(request)

    history = await conv_service.get_history(state["conversation"].conversationId)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].text == "VPN 無法連線"
    assert history[1].role == "assistant"
    assert "VPN 用戶端" in history[1].text


# --------------------------------------------------------------------------
# 18. 多 Issue 不互相阻塞
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_18_multiple_issues_do_not_block_each_other(tmp_path: Path) -> None:
    issue1 = tw.issue(id=1, description="FAILME 案例")
    issue2 = tw.issue(id=2, description="正常案例")
    knowledge = tw.SelectiveFailKnowledgeService()
    workflow, *_ = tw.build_workflow(tmp_path, issues_sequence=[[issue1, issue2]], knowledge=knowledge)

    response = await workflow.respond(tw.make_request("兩個問題"))

    result_types = {r.issueId: r.resultType for r in response.issueResults}
    assert result_types[1] == "FAILED"
    assert result_types[2] == "KNOWLEDGE_ANSWERED"  # issue 1 failing never blocked issue 2


# --------------------------------------------------------------------------
# 19. 每次請求具有 Correlation ID
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_19_every_request_has_a_correlation_id(tmp_path: Path) -> None:
    it_issue = tw.issue(id=1, description="VPN 無法連線")
    knowledge = tw.FakeKnowledgeService(default=KnowledgeResult(found=True, answer="答案", backend="HYBRID"))
    workflow, *_ = tw.build_workflow(tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge)

    # Case 1: caller doesn't supply one -> the workflow derives exactly one.
    auto_response = await workflow.respond(tw.make_request("VPN 無法連線"))
    assert auto_response.correlationId
    assert auto_response.traceId == auto_response.correlationId

    # Case 2: caller supplies one -> it propagates unchanged, never regenerated.
    workflow2, *_ = tw.build_workflow(tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge)
    explicit_response = await workflow2.respond(
        tw.make_request("VPN 無法連線", correlation_id="caller-supplied-id")
    )
    assert explicit_response.correlationId == "caller-supplied-id"


# --------------------------------------------------------------------------
# 20. 回答後可收集使用者回饋
# --------------------------------------------------------------------------


def test_acceptance_20_feedback_can_be_collected_after_an_answer(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "vpn.md").write_text(
        "# VPN 處理方式\n\nVPN 密碼被鎖時，請聯繫資訊服務窗口協助解鎖。",
        encoding="utf-8",
    )
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
        min_score=0.05,
    )
    with TestClient(create_app(settings)) as client:
        chat_response = client.post(
            "/agent/chat",
            json={
                "requestId": "request-1",
                "channel": "msteams",
                "conversation": {"tenantId": "tenant-1", "conversationId": "conversation-1"},
                "user": {"entraObjectId": "user-1", "groups": []},
                "message": {"text": "VPN 密碼被鎖怎麼辦？", "locale": "zh-TW"},
            },
        )
        assert chat_response.status_code == 200
        assert chat_response.json()["feedbackEnabled"] is True

        feedback_response = client.post(
            "/feedback",
            json={
                "correlationId": chat_response.json()["correlationId"],
                "conversationId": "conversation-1",
                "issueId": 1,
                "rating": "UP",
                "userId": "user-1",
            },
        )

    assert feedback_response.status_code == 200
    assert feedback_response.json() == {"status": "recorded"}
