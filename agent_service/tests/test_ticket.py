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
    AgenticTicketItemSelector,
    DisabledTicketService,
    HttpTicketService,
    TicketCatalogError,
    TicketItemSelectionDecision,
    TicketServiceDisabledError,
    TicketServiceError,
    TicketServiceTimeout,
    UntrustedRequesterError,
    build_ticket_service,
    parse_ticket_items_payload,
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


class FakeCatalogModel:
    def __init__(self, result: TicketItemSelectionDecision | Exception) -> None:
        self.result = result
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        outer = self

        class Handle:
            async def ainvoke(self, _messages):
                if isinstance(outer.result, Exception):
                    raise outer.result
                return outer.result

        return Handle()


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
            json={
                "Code": "000000",
                "Msg": "successful",
                "Data": {
                    "items": [
                        {
                            "id": "network",
                            "level": 1,
                            "name": "系統服務",
                            "children": [
                                {
                                    "id": "network-service",
                                    "level": 2,
                                    "name": "網路服務",
                                    "children": [
                                        {
                                            "id": "item-vpn",
                                            "level": 3,
                                            "name": "VPN 無法連線",
                                            "children": [],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                },
            },
        )

    client = _client_with_handler(handler)
    service = HttpTicketService("https://ticket.internal", client=client)

    items = await service.get_ticket_items()

    assert items == [
        TicketItem(
            id="item-vpn",
            name="VPN 無法連線",
            level=3,
            path=["系統服務", "網路服務", "VPN 無法連線"],
        )
    ]


def test_ticket_catalog_keeps_legacy_flat_array_compatible() -> None:
    assert parse_ticket_items_payload([{"id": "legacy", "name": "General"}]) == [
        TicketItem(id="legacy", name="General", level=1, path=["General"])
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"Code": "999999", "Msg": "failed", "Data": None},
        {"Code": "000000", "Msg": "successful"},
        {"Code": "000000", "Data": {"items": "not-an-array"}},
        {"Code": "000000", "Data": {"items": [{"id": "x", "name": "X", "children": {}}]}},
    ],
)
def test_ticket_catalog_rejects_unsuccessful_or_malformed_payload(payload) -> None:
    with pytest.raises(TicketCatalogError):
        parse_ticket_items_payload(payload)


@pytest.mark.asyncio
async def test_agentic_ticket_selector_returns_valid_backend_catalog_id() -> None:
    items = [
        TicketItem(id="system-function", name="系統功能異常", level=3),
        TicketItem(id="vpn", name="VPN 無法連線", level=3),
    ]
    model = FakeCatalogModel(
        TicketItemSelectionDecision(
            ticket_item_id="system-function",
            confidence="HIGH",
            needs_clarification=False,
        )
    )

    selection = await AgenticTicketItemSelector(model).select(
        items=items,
        issue_description="SAP Crystal Reports 授權到期無法開啟",
    )

    assert selection.item is items[0]
    assert selection.reason == "selected"
    assert model.schemas == [TicketItemSelectionDecision]


@pytest.mark.asyncio
async def test_agentic_ticket_selector_rejects_hallucinated_catalog_id() -> None:
    items = [TicketItem(id="vpn", name="VPN 無法連線", level=3)]
    model = FakeCatalogModel(
        TicketItemSelectionDecision(
            ticket_item_id="invented-id",
            confidence="HIGH",
            needs_clarification=False,
        )
    )

    selection = await AgenticTicketItemSelector(model).select(
        items=items,
        issue_description="任何問題",
    )

    assert selection.item is None
    assert selection.reason == "invalid_catalog_id"


@pytest.mark.asyncio
async def test_agentic_ticket_selector_model_unavailable_returns_none() -> None:
    selection = await AgenticTicketItemSelector(None).select(
        items=[TicketItem(id="vpn", name="VPN 無法連線", level=3)],
        issue_description="任何問題",
    )

    assert selection.item is None
    assert selection.reason == "model_unavailable"


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
