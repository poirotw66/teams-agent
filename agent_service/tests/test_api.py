from pathlib import Path

from fastapi.testclient import TestClient

from agent_service.api import create_app
from agent_service.settings import RagSettings


def make_settings(tmp_path: Path, token: str | None = None) -> RagSettings:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "vpn.md").write_text(
        "# VPN 處理方式\n\nVPN 密碼被鎖時，請聯繫資訊服務窗口協助解鎖。",
        encoding="utf-8",
    )
    return RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
        min_score=0.05,
        service_token=token,
    )


def test_ready_and_chat_endpoints(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        ready = client.get("/readyz")
        response = client.post(
            "/agent/chat",
            json={
                "requestId": "request-1",
                "channel": "msteams",
                "conversation": {
                    "tenantId": "tenant-1",
                    "conversationId": "conversation-1",
                },
                "user": {"entraObjectId": "user-1", "groups": []},
                "message": {
                    "text": "VPN 密碼被鎖怎麼辦？",
                    "locale": "zh-TW",
                },
            },
        )

    assert ready.status_code == 200
    assert ready.json()["chunks"] == 1
    assert response.status_code == 200
    assert "VPN 密碼被鎖" in response.json()["answer"]
    assert response.json()["citations"][0]["title"] == "VPN 處理方式"


def test_service_token_is_required_when_configured(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, token="test-token"))) as client:
        rejected = client.post(
            "/retrieval/search",
            json={"query": "VPN", "groups": [], "limit": 1},
        )
        accepted = client.post(
            "/retrieval/search",
            headers={"Authorization": "Bearer test-token"},
            json={"query": "VPN", "groups": [], "limit": 1},
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
