"""Golden User Journeys (docs/0919-arch-1.md).

Named product gate: user entry → exit must not break after refactors.

Boundary: real ``AgentWorkflow`` (or ``/agent/chat`` + ``/feedback``) with
fake externals only. Assert final observable behavior — not node internals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import test_knowledge as tk
import test_workflow as tw
from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.contracts import Citation, FaqEntry, KnowledgeResult
from agent_service.conversation import ConversationService, InMemoryConversationRepository
from agent_service.faq import FaqRepository, FaqService
from agent_service.handoff_flow import HandoffAction
from agent_service.knowledge import HybridKnowledgeService
from agent_service.retrieval import HybridIndex
from agent_service.settings import RagSettings
from agent_service.supervisor import ConversationSupervisorDecision

# --------------------------------------------------------------------------
# 1. Teams knowledge question → RAG → Citation → Answer
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_01_rag_citation_answer(tmp_path: Path) -> None:
    it_issue = tw.issue(id=1, description="VPN 無法連線", route="KNOWLEDGE")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(
            found=True,
            answer="請重新安裝 VPN 用戶端。",
            sources=[Citation(title="VPN 疑難排解手冊", url="https://kb.example/vpn")],
            backend="HYBRID",
        )
    )
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge
    )

    response = await workflow.respond(tw.make_request("VPN 無法連線"))

    assert response.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"
    assert "請重新安裝 VPN 用戶端" in response.answer
    assert response.citations
    assert response.citations[0].title == "VPN 疑難排解手冊"
    assert knowledge.calls == ["VPN 無法連線"]


# --------------------------------------------------------------------------
# 2. FAQ → deterministic answer
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_02_faq_deterministic_answer(tmp_path: Path) -> None:
    entry = FaqEntry(
        id="1", faqKey="PW_RESET", enabled=True, answer="請至公司密碼管理入口重設密碼。"
    )
    faq_service = FaqService(FaqRepository([entry]))
    it_issue = tw.issue(id=1, description="忘記密碼", route="FAQ", faqKey="PW_RESET")
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[[it_issue]], faq_service=faq_service
    )

    response = await workflow.respond(tw.make_request("忘記密碼怎麼辦"))

    assert response.issueResults[0].resultType == "FAQ_ANSWERED"
    assert response.issueResults[0].answer == entry.answer


# --------------------------------------------------------------------------
# 3. Insufficient info → clarification
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_03_insufficient_info_asks_clarification(tmp_path: Path) -> None:
    it_issue = tw.issue(
        id=1,
        description="VPN 問題",
        readiness="NEED_MORE_INFO",
        missingInfo=["使用的 VPN 應用程式名稱", "錯誤訊息或錯誤碼"],
    )
    workflow, *_ = tw.build_workflow(tmp_path, issues_sequence=[[it_issue]])

    response = await workflow.respond(tw.make_request("VPN 有問題"))

    assert response.issueResults[0].resultType == "NEED_MORE_INFO"
    assert len(response.issueResults[0].questions) <= 2
    assert "使用的 VPN 應用程式名稱" in response.answer


# --------------------------------------------------------------------------
# 4. Second turn supplies detail → continues same issue
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_04_follow_up_continues_same_issue(tmp_path: Path) -> None:
    first = tw.issue(
        id=1,
        description="VPN 有問題",
        readiness="NEED_MORE_INFO",
        missingInfo=["使用的 VPN 應用程式名稱"],
    )
    second = tw.issue(id=1, description="Cisco AnyConnect", readiness="READY")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請重新啟動用戶端。", backend="HYBRID")
    )
    workflow, extractor_model, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[first], [second]],
        knowledge=knowledge,
    )

    await workflow.respond(tw.make_request("VPN 有問題"))
    response = await workflow.respond(tw.make_request("Cisco AnyConnect"))

    assert extractor_model.calls == 2
    assert any("VPN 有問題" in text for text in extractor_model.human_messages)
    assert response.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"
    assert "請重新啟動用戶端" in response.answer


# --------------------------------------------------------------------------
# 5. Multi-issue (cap + prioritize notice)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_05_multi_issue_prioritizes(tmp_path: Path) -> None:
    issues = [tw.issue(id=i, description=f"問題{i}") for i in range(1, 5)]
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="OK", backend="HYBRID")
    )
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[issues], knowledge=knowledge
    )

    response = await workflow.respond(tw.make_request("四個問題一次問"))

    assert len(response.issueResults) == 3
    assert "已先協助你處理最重要的" in response.answer


# --------------------------------------------------------------------------
# 6. IT + non-IT mixed message
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_06_mixed_it_and_non_it(tmp_path: Path) -> None:
    issues = [
        tw.issue(id=1, description="VPN 無法登入"),
        tw.issue(
            id=2,
            description="今天午餐吃什麼？",
            isIT=False,
            readiness="NOT_IT",
            route="NOT_IT",
        ),
    ]
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請重試登入。", backend="HYBRID")
    )
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[issues], knowledge=knowledge
    )

    response = await workflow.respond(
        tw.make_request("VPN 無法登入，另外今天午餐吃什麼？")
    )

    assert len(response.issueResults) == 1
    assert response.issueResults[0].issueId == 1
    assert "不在此 IT 助手的服務範圍" in response.answer


# --------------------------------------------------------------------------
# 7. Knowledge miss → no hallucination
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_07_knowledge_miss_no_hallucination(tmp_path: Path) -> None:
    it_issue = tw.issue(id=1, description="不存在的系統問題")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID")
    )
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge
    )

    response = await workflow.respond(tw.make_request("不存在的系統問題"))

    result = response.issueResults[0]
    assert result.resultType == "NO_KNOWLEDGE"
    assert result.answer == ""
    assert result.sources == []
    assert "查無相關資訊" in response.answer


# --------------------------------------------------------------------------
# 8. Knowledge miss → handoff / ticket offer paths
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_08_knowledge_miss_offers_handoff_paths(tmp_path: Path) -> None:
    it_issue = tw.issue(id=1, description="內部量子傳送門錯誤 QZ-999")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=False, answer="", backend="HYBRID")
    )
    workflow, *_ = tw.build_workflow(
        tmp_path, issues_sequence=[[it_issue]], knowledge=knowledge
    )

    response = await workflow.respond(tw.make_request("內部量子傳送門出現錯誤 QZ-999"))

    assert response.issueResults[0].resultType == "NO_KNOWLEDGE"
    answer = response.answer
    assert "查無相關資訊" in answer or "建立派工單" in answer or "線上客服" in answer


# --------------------------------------------------------------------------
# 9. After handoff, agent stops answering until close
# --------------------------------------------------------------------------


class _JourneyHandoffRouter:
    async def decide(self, *, message: str, case_status: str, **_kwargs) -> HandoffAction:
        from agent_service.handoff_flow import is_protocol_close_command

        if case_status == "DEMO_ACTIVE" and is_protocol_close_command(message):
            return HandoffAction.CLOSE
        if case_status == "DEMO_ACTIVE":
            return HandoffAction.HUMAN_MESSAGE
        return HandoffAction.UNKNOWN


class _EscalationSupervisor:
    async def decide(self, *, message: str, **_kwargs):
        if "真人客服" in message:
            return ConversationSupervisorDecision(
                intent="HUMAN_ESCALATION",
                requestedAction="CONTACT_HUMAN",
                confidence=0.95,
            )
        return ConversationSupervisorDecision()


def test_journey_09_handoff_active_agent_stops_answering(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "vpn.md").write_text("# VPN\n\n一般說明。", encoding="utf-8")
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
        min_score=0.05,
        handoff_repository_mode="MEMORY",
    )

    def payload(text: str, request_id: str) -> dict:
        return {
            "requestId": request_id,
            "correlationId": request_id,
            "channel": "msteams",
            "conversation": {
                "tenantId": "tenant-1",
                "conversationId": "journey-handoff-1",
            },
            "user": {
                "entraObjectId": "user-1",
                "teamsUserId": "teams-user-1",
                "displayName": "Tester",
                "email": "tester@example.test",
                "groups": [],
            },
            "message": {"text": text, "locale": "zh-TW"},
        }

    with TestClient(create_app(settings)) as client:
        client.app.state.workflow.supervisor = _EscalationSupervisor()
        client.app.state.workflow.handoff_router = _JourneyHandoffRouter()
        activated = client.post("/agent/chat", json=payload("我要找真人客服", "j9-1"))
        original_extract = client.app.state.workflow.extractor.extract

        async def fail_if_ai_called(*_args, **_kwargs):
            raise AssertionError("DEMO_ACTIVE must bypass the AI workflow")

        client.app.state.workflow.extractor.extract = fail_if_ai_called
        during = client.post("/agent/chat", json=payload("補充錯誤碼 691", "j9-2"))
        closed = client.post("/agent/chat", json=payload("/close", "j9-3"))
        client.app.state.workflow.extractor.extract = original_extract

    assert activated.status_code == 200
    assert "真人客服模式" in activated.json()["answer"]
    assert during.status_code == 200
    assert "不會實際傳送給客服人員" in during.json()["answer"]
    assert closed.status_code == 200
    assert "已結束" in closed.json()["answer"]


# --------------------------------------------------------------------------
# 10. Feedback 👍 / 👎
# --------------------------------------------------------------------------


def test_journey_10_feedback_after_answer(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "vpn.md").write_text(
        "# VPN\n\nVPN 密碼被鎖時，請聯繫資訊服務窗口。", encoding="utf-8"
    )
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
        min_score=0.05,
    )
    with TestClient(create_app(settings)) as client:
        chat = client.post(
            "/agent/chat",
            json={
                "requestId": "j10-1",
                "channel": "msteams",
                "conversation": {
                    "tenantId": "tenant-1",
                    "conversationId": "journey-feedback-1",
                },
                "user": {"entraObjectId": "user-1", "groups": []},
                "message": {"text": "VPN 密碼被鎖怎麼辦？", "locale": "zh-TW"},
            },
        )
        assert chat.status_code == 200
        body = chat.json()
        assert body["feedbackEnabled"] is True

        feedback = client.post(
            "/feedback",
            json={
                "correlationId": body["correlationId"],
                "conversationId": "journey-feedback-1",
                "issueId": 1,
                "rating": "UP",
                "userId": "user-1",
            },
        )
        assert feedback.status_code == 200
        assert feedback.json() == {"status": "recorded"}


# --------------------------------------------------------------------------
# 11. Restricted document ACL
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_11_restricted_document_acl(tmp_path: Path) -> None:
    from test_security import restricted_chunk

    restricted = restricted_chunk()
    public = tk.vpn_chunk(content="VPN 一般密碼重設方式，公開文件。")
    it_issue = tw.issue(
        id=1,
        description="VPN 特殊權限怎麼設定？",
        route="KNOWLEDGE",
        readiness="READY",
    )
    unauthorized = tw.trusted_user(groups=["HR"])
    authorized = tw.trusted_user(groups=["IT"])

    unauthorized_workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[it_issue]],
        knowledge=HybridKnowledgeService(
            tk.make_settings(tmp_path),
            HybridIndex([restricted, public]),
            model=tk.FakeChatModel(
                relevant=True,
                answer_text="VPN 特殊權限請依內部流程設定 [S1]",
            ),
        ),
    )
    authorized_workflow, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[it_issue]],
        knowledge=HybridKnowledgeService(
            tk.make_settings(tmp_path),
            HybridIndex([restricted, public]),
            model=tk.FakeChatModel(
                relevant=True,
                answer_text="VPN 特殊權限請依內部流程設定 [S1]",
            ),
        ),
    )
    unauthorized_workflow._governed_answer_model = lambda: None  # type: ignore[method-assign]
    authorized_workflow._governed_answer_model = lambda: None  # type: ignore[method-assign]

    denied = await unauthorized_workflow.respond(
        tw.make_request(
            "VPN 特殊權限怎麼設定？",
            user=unauthorized,
            conversation_id="journey-acl-a",
        )
    )
    allowed = await authorized_workflow.respond(
        tw.make_request(
            "VPN 特殊權限怎麼設定？",
            user=authorized,
            conversation_id="journey-acl-b",
        )
    )

    assert restricted.title not in denied.answer
    assert all(c.title != restricted.title for c in denied.citations)
    assert any(c.title == restricted.title for c in allowed.citations)


# --------------------------------------------------------------------------
# 12. Conversation timeout → new conversation
# --------------------------------------------------------------------------


class _JourneyClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._now

    def advance_hours(self, hours: float) -> None:
        from datetime import timedelta

        self._now = self._now + timedelta(hours=hours)


@pytest.mark.asyncio
async def test_journey_12_conversation_timeout_starts_fresh(tmp_path: Path) -> None:
    clock = _JourneyClock()
    first = tw.issue(id=1, description="VPN 有問題", readiness="READY")
    second = tw.issue(id=1, description="Outlook 無法寄信", readiness="READY")
    knowledge = tw.FakeKnowledgeService(
        default=KnowledgeResult(found=True, answer="請依手冊操作。", backend="HYBRID")
    )
    settings = tw.make_settings(tmp_path, conversation_timeout_hours=1)
    repository = InMemoryConversationRepository(clock=clock)
    conv_service = ConversationService(repository, settings, clock=clock)
    workflow, extractor_model, *_ = tw.build_workflow(
        tmp_path,
        issues_sequence=[[first], [second]],
        knowledge=knowledge,
        conversation_service=conv_service,
        settings_overrides={"conversation_timeout_hours": 1},
    )

    first_response = await workflow.respond(
        tw.make_request("VPN 有問題", conversation_id="teams-conv-timeout")
    )
    before = await conv_service.load_or_create(
        tenant_id="tenant-1",
        teams_conversation_id="teams-conv-timeout",
        teams_user_id="user-1",
    )
    before_id = before.conversationId

    clock.advance_hours(2)

    second_response = await workflow.respond(
        tw.make_request("Outlook 無法寄信", conversation_id="teams-conv-timeout")
    )
    after = await conv_service.load_or_create(
        tenant_id="tenant-1",
        teams_conversation_id="teams-conv-timeout",
        teams_user_id="user-1",
    )

    assert first_response.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"
    assert second_response.issueResults[0].resultType == "KNOWLEDGE_ANSWERED"
    assert after.conversationId != before_id
    assert extractor_model.calls == 2
    # Fresh conversation: second extractor prompt must not carry turn-1 history.
    assert "VPN 有問題" not in extractor_model.human_messages[-1]
