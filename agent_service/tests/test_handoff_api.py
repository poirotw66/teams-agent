from pathlib import Path

from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.contracts import Ticket, TicketItem
from agent_service.handoff import HandoffStatus
from agent_service.settings import RagSettings


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


def test_explicit_human_demo_lifecycle_and_close_restore_ai(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        offered = client.post(
            "/agent/chat", json=payload("我要找真人客服", "request-1")
        )
        activated = client.post(
            "/agent/chat", json=payload("聯絡線上客服", "request-2")
        )

        original_extract = client.app.state.workflow.extractor.extract

        async def fail_if_ai_is_called(*_args, **_kwargs):
            raise AssertionError("DEMO_ACTIVE must bypass the AI workflow")

        client.app.state.workflow.extractor.extract = fail_if_ai_is_called
        demo_message = client.post(
            "/agent/chat", json=payload("補充錯誤碼 691", "request-3")
        )
        closed = client.post("/agent/chat", json=payload("/close", "request-4"))
        client.app.state.workflow.extractor.extract = original_extract
        resumed = client.post(
            "/agent/chat", json=payload("VPN 密碼被鎖", "request-5")
        )
        repository = client.app.state.handoff_repository
        case = next(iter(repository._cases.values()))

    assert offered.status_code == 200
    assert "建立工單" in offered.json()["answer"]
    assert "聯絡線上客服" in offered.json()["answer"]
    assert activated.status_code == 200
    assert "真人客服模式（Demo）" in activated.json()["answer"]
    assert demo_message.status_code == 200
    assert "不會實際傳送給客服人員" in demo_message.json()["answer"]
    assert closed.status_code == 200
    assert "已結束" in closed.json()["answer"]
    assert resumed.status_code == 200
    assert "VPN" in resumed.json()["answer"]
    assert case.status == HandoffStatus.CLOSED


def test_duplicate_close_is_idempotent_and_does_not_enter_ai(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        first = client.post("/agent/chat", json=payload("/close", "request-1"))
        second = client.post("/agent/chat", json=payload("/close", "request-2"))

    assert first.status_code == second.status_code == 200
    assert first.json()["answer"] == second.json()["answer"]


def test_no_knowledge_offers_ticket_and_human_paths(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.post(
            "/agent/chat",
            json=payload("內部量子傳送門出現錯誤 QZ-999", "request-1"),
        )

    assert response.status_code == 200
    assert "建立工單" in response.json()["answer"]
    assert "聯絡線上客服" in response.json()["answer"]


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
    with TestClient(create_app(make_settings(tmp_path))) as client:
        client.app.state.workflow.ticket_service = fake
        client.post("/agent/chat", json=payload("我要找真人客服", "request-1"))
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
