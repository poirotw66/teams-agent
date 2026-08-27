import os

from fastapi.testclient import TestClient

from teams_agent import mock_ticket_service


def test_mock_ticket_create_and_owner_scoped_lookup() -> None:
    os.environ.pop("MOCK_TICKET_TOKEN", None)
    os.environ.pop("MOCK_TICKET_STORE_MODE", None)
    os.environ.pop("MOCK_TICKET_PUBLIC_BASE_URL", None)
    mock_ticket_service._tickets.clear()
    client = TestClient(mock_ticket_service.app)
    response = client.post(
        "/tickets",
        json={
            "requesterId": "user-1",
            "requesterName": "Test User",
            "requesterEmail": "test@example.com",
            "title": "VPN 無法連線",
            "description": "VPN 無法連線",
            "ticketItemId": "NETWORK",
            "priority": "NORMAL",
        },
    )

    assert response.status_code == 201
    ticket_id = response.json()["id"]
    assert ticket_id.startswith("MOCK-")
    assert client.get("/tickets", params={"requesterId": "user-1"}).json()[0][
        "id"
    ] == ticket_id
    assert client.get("/tickets", params={"requesterId": "user-2"}).json() == []
    assert client.get(f"/tickets/{ticket_id}").json()["id"] == ticket_id
    assert (
        client.get(
            f"/tickets/{ticket_id}", params={"requesterId": "user-2"}
        ).status_code
        == 404
    )


def test_mock_ticket_uses_configured_public_base_url(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_TICKET_PUBLIC_BASE_URL", "https://tickets.example.test/")
    client = TestClient(mock_ticket_service.app)

    response = client.post(
        "/tickets",
        json={
            "requesterId": "user-1",
            "requesterName": "Test User",
            "requesterEmail": "test@example.com",
            "title": "SAP 密碼重置",
            "description": "SAP 密碼重置",
            "ticketItemId": "ACCESS",
        },
    )

    assert response.json()["url"].startswith(
        "https://tickets.example.test/tickets/MOCK-"
    )


def test_mock_ticket_api_requires_configured_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_TICKET_TOKEN", "test-secret-token")
    client = TestClient(mock_ticket_service.app)

    assert client.get("/healthz").status_code == 200
    assert client.get("/ticket-items").status_code == 401
    assert (
        client.get(
            "/ticket-items",
            headers={"authorization": "Bearer test-secret-token"},
        ).status_code
        == 200
    )
