import pytest
from fake_firestore import FakeFirestoreClient

from agent_service.settings import RagSettings
from agent_service.ticket_dedupe import (
    FirestoreTicketRequestDedupeRepository,
    InMemoryTicketRequestDedupeRepository,
    build_ticket_request_dedupe,
)


@pytest.mark.asyncio
async def test_in_memory_ticket_dedupe_is_idempotent() -> None:
    repo = InMemoryTicketRequestDedupeRepository()

    await repo.put("tenant-1", "req-1", "TCK-1")
    await repo.put("tenant-1", "req-1", "TCK-2")

    assert await repo.get_ticket_id("tenant-1", "req-1") == "TCK-1"


@pytest.mark.asyncio
async def test_firestore_ticket_dedupe_persists_ticket_id() -> None:
    client = FakeFirestoreClient()
    repo = FirestoreTicketRequestDedupeRepository(
        client,
        collection="ticket_request_ledger",
        retention_days=30,
    )

    await repo.put("tenant-1", "req-1", "TCK-1")
    await repo.put("tenant-1", "req-1", "TCK-2")

    assert await repo.get_ticket_id("tenant-1", "req-1") == "TCK-1"
    assert client.document_count("ticket_request_ledger/") == 1


def test_build_ticket_request_dedupe_uses_memory_by_default(tmp_path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "chunks.json",
        auto_build_index=False,
    )

    repo = build_ticket_request_dedupe(settings, firestore_client=FakeFirestoreClient())

    assert isinstance(repo, InMemoryTicketRequestDedupeRepository)
