from pathlib import Path

from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.contracts import Ticket, TicketItem
from agent_service.handoff import HandoffStatus
from agent_service.handoff_flow import HandoffAction
from agent_service.settings import RagSettings
from agent_service.supervisor import ConversationSupervisorDecision
from agent_service.ticket import TicketItemSelection


def make_settings(tmp_path: Path) -> RagSettings:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "vpn.md").write_text(
        "# VPN\n\nVPN 密碼鎖定時請聯繫資訊服務窗口。", encoding="utf-8"
    )
    return RagSettings(
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
            "conversationId": "conversation-1",
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


class FakeHandoffRouter:
    def __init__(self, actions: list[HandoffAction]) -> None:
        self.actions = list(actions)

    async def decide(self, **_kwargs) -> HandoffAction:
        return self.actions.pop(0)


class StubSupervisor:
    async def decide(self, *, message: str, pending_clarification: bool = False, recent_turns=None):
        _ = (pending_clarification, recent_turns)
        if "真人客服" in message:
            return ConversationSupervisorDecision(
                intent="HUMAN_ESCALATION",
                requestedAction="CONTACT_HUMAN",
                confidence=0.95,
            )
        return ConversationSupervisorDecision()


def test_explicit_human_demo_lifecycle_and_close_restore_ai(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        client.app.state.workflow.supervisor = StubSupervisor()
        client.app.state.workflow.handoff_router = FakeHandoffRouter(
            [HandoffAction.HUMAN_MESSAGE, HandoffAction.CLOSE]
        )
        activated = client.post(
            "/agent/chat", json=payload("我要找真人客服", "request-1")
        )

        original_extract = client.app.state.workflow.extractor.extract

        async def fail_if_ai_is_called(*_args, **_kwargs):
            raise AssertionError("DEMO_ACTIVE must bypass the AI workflow")

        client.app.state.workflow.extractor.extract = fail_if_ai_is_called
        demo_message = client.post(
            "/agent/chat", json=payload("補充錯誤碼 691", "request-2")
        )
        closed = client.post("/agent/chat", json=payload("/close", "request-3"))
        client.app.state.workflow.extractor.extract = original_extract
        resumed = client.post(
            "/agent/chat", json=payload("VPN 密碼被鎖", "request-4")
        )
        repository = client.app.state.handoff_repository
        case = next(iter(repository._cases.values()))

    assert activated.status_code == 200
    assert "真人客服模式（Demo）" in activated.json()["answer"]
    assert demo_message.status_code == 200
    assert "不會實際傳送給客服人員" in demo_message.json()["answer"]
    assert closed.status_code == 200
    assert "已結束" in closed.json()["answer"]
    assert resumed.status_code == 200
    assert "VPN" in resumed.json()["answer"]
    assert case.status == HandoffStatus.CLOSED


def test_no_knowledge_offers_ticket_and_human_paths(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.post(
            "/agent/chat",
            json=payload("內部量子傳送門出現錯誤 QZ-999", "request-1"),
        )

    assert response.status_code == 200
    assert "建立派工單" in response.json()["answer"]
    assert "聯絡線上客服" in response.json()["answer"]


def test_new_it_question_does_not_mutate_pending_handoff_summary(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        offered = client.post(
            "/agent/chat",
            json=payload("SAP Crystal Reports 授權到期無法開啟", "request-1"),
        )
        client.app.state.workflow.handoff_router = FakeHandoffRouter(
            [HandoffAction.NEW_ISSUE]
        )
        answered = client.post(
            "/agent/chat",
            json=payload("VPN 密碼鎖住怎麼辦", "request-2"),
        )
        repository = client.app.state.handoff_repository
        cases = list(repository._cases.values())

    assert offered.status_code == answered.status_code == 200
    assert "問題：SAP Crystal Reports 授權到期無法開啟" in offered.json()["answer"]
    assert "VPN 密碼鎖定時請聯繫資訊服務窗口" in answered.json()["answer"]
    assert "SAP Crystal Reports" not in answered.json()["answer"]
    assert cases[0].status == HandoffStatus.CANCELLED


def test_ticket_path_uses_confirmed_handoff_summary(tmp_path: Path) -> None:
    class FakeTicketService:
        def __init__(self):
            self.drafts = []

        async def get_ticket_items(self, **_kwargs):
            return [TicketItem(id="GENERAL", name="General")]

        async def create_ticket(self, draft, **_kwargs):
            self.drafts.append(draft)
            return Ticket(id="MOCK-1001", title=draft.title, status="OPEN")

    fake = FakeTicketService()

    class FakeTicketItemSelector:
        async def select(self, *, items, issue_description, execution_context=None):
            return TicketItemSelection(item=items[0], reason="selected")

    with TestClient(create_app(make_settings(tmp_path))) as client:
        client.app.state.workflow.ticket_service = fake
        client.app.state.workflow.ticket_item_selector = FakeTicketItemSelector()
        client.post("/agent/chat", json=payload("我要找真人客服", "request-1"))
        client.app.state.workflow.handoff_router = FakeHandoffRouter(
            [HandoffAction.CREATE_TICKET]
        )
        created = client.post(
            "/agent/chat", json=payload("建立工單", "request-2")
        )
        repository = client.app.state.handoff_repository
        case = next(iter(repository._cases.values()))

    assert created.status_code == 200
    assert "MOCK-1001" in created.json()["answer"]
    assert case.status == HandoffStatus.ROUTED_TO_TICKET
    assert case.summary.confirmedBy == "user-1"
    assert case.summary.issue in fake.drafts[0].description
