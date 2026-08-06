"""Tests for the Ticket Service adapter (spec §11, §18.5).

No network access is performed: HttpTicketService is always constructed
with an httpx.AsyncClient wired to an httpx.MockTransport.
"""

import json
import logging

import httpx
import pytest

from agent_service.contracts import Ticket, TicketDraft, TicketItem
from agent_service.settings import RagSettings
from agent_service.ticket import (
    DisabledTicketService,
    HttpTicketService,
    TicketServiceDisabledError,
    TicketServiceError,
    TicketServiceTimeout,
    UntrustedRequesterError,
    build_ticket_service,
)

SECRET_TOKEN = "super-secret-ticket-token"


def _trusted_draft(**overrides) -> TicketDraft:
    fields = {
        "requesterId": "entra-obj-1",
        "requesterName": "Alice Chen",
        "requesterEmail": "alice@example.com",
        "title": "VPN 無法連線",
        "description": "使用者反映無法連線 VPN",
        "ticketItemId": "item-vpn",
        "priority": "NORMAL",
    }
    fields.update(overrides)
    return TicketDraft(**fields)


def _client_with_handler(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="https://ticket.internal")


# --- DISABLED mode -----------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_service_raises_on_every_operation() -> None:
    service = DisabledTicketService()
    draft = _trusted_draft()

    with pytest.raises(TicketServiceDisabledError):
        await service.get_ticket_items()
    with pytest.raises(TicketServiceDisabledError):
        await service.create_ticket(draft)
    with pytest.raises(TicketServiceDisabledError):
        await service.list_tickets_by_requester("entra-obj-1")
    with pytest.raises(TicketServiceDisabledError):
        await service.get_ticket("t-1", "entra-obj-1")


def test_build_ticket_service_disabled_mode(tmp_path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        ticket_service_mode="DISABLED",
    )
    service = build_ticket_service(settings)
    assert isinstance(service, DisabledTicketService)


def test_build_ticket_service_http_mode(tmp_path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        ticket_service_mode="HTTP",
        ticket_service_base_url="https://ticket.internal",
    )
    service = build_ticket_service(settings)
    assert isinstance(service, HttpTicketService)


# --- create_ticket -------------------------------------------------------


@pytest.mark.asyncio
async def test_create_ticket_with_trusted_identity_succeeds() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/tickets"
        body = json.loads(request.content)
        assert body["requesterId"] == "entra-obj-1"
        return httpx.Response(
            201,
            json={
                "id": "t-100",
                "title": "VPN 無法連線",
                "status": "OPEN",
                "requesterId": "entra-obj-1",
            },
        )

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    ticket = await service.create_ticket(_trusted_draft())

    assert isinstance(ticket, Ticket)
    assert ticket.id == "t-100"
    assert ticket.status == "OPEN"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"requesterId": ""},
        {"requesterName": ""},
        {"requesterEmail": ""},
        {"requesterId": "   "},
    ],
)
@pytest.mark.asyncio
async def test_create_ticket_with_missing_identity_raises_before_http_call(
    overrides: dict,
) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(201, json={"id": "t-1", "title": "x", "status": "OPEN"})

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    with pytest.raises(UntrustedRequesterError):
        await service.create_ticket(_trusted_draft(**overrides))

    assert called is False


# --- list / get: ownership enforcement -----------------------------------


@pytest.mark.asyncio
async def test_list_tickets_by_requester_returns_only_own_tickets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["requesterId"] == "entra-obj-1"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "t-1",
                    "title": "A",
                    "status": "OPEN",
                    "requesterId": "entra-obj-1",
                },
                # Backend misbehaving / permissive: includes another user's
                # ticket even though we scoped the query. Adapter must
                # filter it out (defense in depth, spec §17).
                {
                    "id": "t-2",
                    "title": "B",
                    "status": "OPEN",
                    "requesterId": "someone-else",
                },
            ],
        )

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    tickets = await service.list_tickets_by_requester("entra-obj-1")

    assert [t.id for t in tickets] == ["t-1"]


@pytest.mark.asyncio
async def test_get_ticket_own_ticket_returns_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tickets/t-1"
        assert request.url.params["requesterId"] == "entra-obj-1"
        return httpx.Response(
            200,
            json={
                "id": "t-1",
                "title": "A",
                "status": "OPEN",
                "requesterId": "entra-obj-1",
            },
        )

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    ticket = await service.get_ticket("t-1", "entra-obj-1")

    assert ticket is not None
    assert ticket.id == "t-1"


@pytest.mark.asyncio
async def test_get_ticket_cross_user_is_refused_even_if_backend_returns_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Simulate a permissive/buggy backend that ignores the requesterId
        # filter and returns someone else's ticket anyway.
        return httpx.Response(
            200,
            json={
                "id": "t-99",
                "title": "Someone else's ticket",
                "status": "OPEN",
                "requesterId": "someone-else",
            },
        )

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    ticket = await service.get_ticket("t-99", "entra-obj-1")

    assert ticket is None


# --- get_ticket_items -----------------------------------------------------


@pytest.mark.asyncio
async def test_get_ticket_items_parses_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ticket-items"
        return httpx.Response(
            200,
            json=[
                {"id": "item-vpn", "name": "VPN"},
                {"id": "item-laptop", "name": "Laptop"},
            ],
        )

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    items = await service.get_ticket_items()

    assert items == [
        TicketItem(id="item-vpn", name="VPN"),
        TicketItem(id="item-laptop", name="Laptop"),
    ]


# --- error handling --------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_raises_typed_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    with pytest.raises(TicketServiceTimeout):
        await service.get_ticket_items()


@pytest.mark.asyncio
async def test_server_error_raises_typed_error_with_status_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    with pytest.raises(TicketServiceError) as exc_info:
        await service.get_ticket_items()

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_client_error_raises_typed_error_with_status_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    with pytest.raises(TicketServiceError) as exc_info:
        await service.get_ticket("missing", "entra-obj-1")

    assert exc_info.value.status_code == 404


# --- security: token must never be logged ---------------------------------


@pytest.mark.asyncio
async def test_token_never_appears_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Confirm the token IS sent on the wire (functionality intact)...
        assert request.headers.get("Authorization") == f"Bearer {SECRET_TOKEN}"
        # ...but the response is a failure, to force the error-logging path.
        return httpx.Response(500, json={"error": "boom"})

    client = _client_with_handler(handler)
    service = HttpTicketService(
        "https://ticket.internal", token=SECRET_TOKEN, client=client
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(TicketServiceError):
        await service.get_ticket_items()

    for record in caplog.records:
        assert SECRET_TOKEN not in record.getMessage()
        assert SECRET_TOKEN not in str(record.__dict__)
