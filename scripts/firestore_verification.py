#!/usr/bin/env python3
"""Live verification probe for FirestoreConversationRepository (spec §10.3).

Why this exists: every Firestore test in
``agent_service/tests/test_conversation.py`` drives an in-process Fake
client. That Fake is pinned to the real SDK's *signatures*, but signatures
cannot tell you whether the real service actually honors what the
repository assumes:

1. The ordered ``limit``-ed read of the ``messages`` **subcollection**
   returns messages newest-first without any composite index having to be
   created out-of-band. This check has already earned its keep: the
   repository first ordered by ``__name__`` descending, which the Fake
   accepted and live Firestore rejected with FAILED_PRECONDITION ("the
   query requires an index"). Ordering moved to the regular ``sortKey``
   field, which gets an automatic single-field index in both directions.
2. ``set(..., merge=True)`` updates ``lastActivityAt``/``expiresAt`` without
   dropping the rest of the conversation document.
3. Timestamps survive the round trip as aware datetimes (Firestore returns
   ``DatetimeWithNanoseconds``), so ``_is_timed_out`` compares correctly.
4. A second repository instance -- i.e. a different Cloud Run instance --
   sees the first one's conversation. This is the whole reason FIRESTORE
   mode exists.

Everything is written into a throwaway collection named
``verify_<timestamp>_<random>`` and deleted at the end, including on
failure. The script never touches the ``conversations`` collection that a
real deployment uses.

Usage:
    gcloud auth application-default login   # if ADC is not set up
    cd agent_service
    .venv/bin/python ../scripts/firestore_verification.py \
        --project itr-aimasteryhub-lab

Requires the google-cloud-firestore SDK (agent_service `firestore` extra),
ADC credentials, and network access.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent_service" / "src"))

from agent_service.contracts import ConversationMessage
from agent_service.conversation import (
    FirestoreConversationRepository,
)

KEY = {
    "tenant_id": "verify-tenant",
    "teams_conversation_id": "verify-conversation",
    "teams_user_id": "verify-user",
}


class Results:
    """Collects pass/fail lines so one failure does not hide the rest."""

    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, passed, detail))
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {name}{f' -- {detail}' if detail else ''}")

    @property
    def failed(self) -> int:
        return sum(1 for _, passed, _ in self.checks if not passed)


async def verify(repository_factory, collection: str, results: Results) -> str:
    """Run every check; returns the conversation id it created."""
    repo = repository_factory()

    # -- 1. create + find round trip ---------------------------------
    created = await repo.create_conversation(**KEY)
    found = await repo.find_conversation(**KEY, timeout_hours=24)
    results.record(
        "create then find returns the same conversation",
        found is not None and found.conversationId == created.conversationId,
        f"conversation_id={created.conversationId}",
    )

    # -- 2. timestamps survive the round trip ------------------------
    results.record(
        "timestamps come back as aware datetimes",
        found is not None
        and isinstance(found.startedAt, datetime)
        and found.startedAt.tzinfo is not None,
        f"startedAt={found.startedAt!r}" if found else "",
    )

    # -- 3. ordered subcollection read without a composite index -----
    # Written back-to-back on purpose: this is where a naive
    # timestamp-only ordering would go non-deterministic.
    texts = [f"message-{i}" for i in range(6)]
    for text in texts:
        await repo.save_message(
            created.conversationId,
            ConversationMessage(
                role="user", text=text, createdAt=datetime.now(timezone.utc)
            ),
        )

    try:
        recent = await repo.get_recent_messages(created.conversationId, limit=10)
        ordering_ok = [m.text for m in recent] == texts
        detail = "" if ordering_ok else f"got {[m.text for m in recent]}"
    except Exception as exc:  # noqa: BLE001 - the point is to report, not raise
        ordering_ok = False
        detail = f"{type(exc).__name__}: {exc}"
    results.record(
        "subcollection ordered read needs no composite index", ordering_ok, detail
    )

    tail = await repo.get_recent_messages(created.conversationId, limit=2)
    results.record(
        "limit returns the newest tail, oldest-first",
        [m.text for m in tail] == texts[-2:],
        f"got {[m.text for m in tail]}",
    )

    # -- 4. merge=True preserves the untouched fields ----------------
    refreshed = await repo.find_conversation(**KEY, timeout_hours=24)
    results.record(
        "merge=True kept startedAt while advancing lastActivityAt",
        refreshed is not None
        and refreshed.startedAt == created.startedAt
        and refreshed.lastActivityAt > created.startedAt,
        f"startedAt={refreshed.startedAt} lastActivityAt={refreshed.lastActivityAt}"
        if refreshed
        else "",
    )

    # -- 5. the message tail is attached to the context --------------
    results.record(
        "find_conversation attaches the message tail",
        refreshed is not None
        and bool(refreshed.messages)
        and refreshed.messages[-1].text == texts[-1],
        f"last={refreshed.messages[-1].text!r}" if refreshed and refreshed.messages else "",
    )

    # -- 6. a fresh instance sees it (the reason FIRESTORE exists) ---
    other_instance = repository_factory()
    seen = await other_instance.find_conversation(**KEY, timeout_hours=24)
    results.record(
        "a second repository instance sees the conversation",
        seen is not None and seen.conversationId == created.conversationId,
    )

    # -- 7. timeout is enforced in code, not by TTL ------------------
    timed_out = await repo.find_conversation(**KEY, timeout_hours=0)
    results.record(
        "an expired conversation reads as absent while still stored",
        timed_out is None,
    )

    # -- 8. unknown conversation is rejected -------------------------
    try:
        await repo.save_message(
            "definitely-not-a-conversation",
            ConversationMessage(
                role="user", text="orphan", createdAt=datetime.now(timezone.utc)
            ),
        )
        rejected = False
    except LookupError:
        rejected = True
    results.record("save_message rejects an unknown conversation id", rejected)

    return created.conversationId


async def verify_ttl_field(client, collection: str, conversation_id: str, results: Results) -> None:
    """Read the raw document: expiresAt must be there for the TTL policy."""
    snapshot = await client.collection(collection).document(conversation_id).get()
    expires_at = (snapshot.to_dict() or {}).get("expiresAt")
    results.record(
        "expiresAt is written for the TTL policy",
        isinstance(expires_at, datetime)
        and expires_at > datetime.now(timezone.utc) + timedelta(hours=23),
        f"expiresAt={expires_at!r}",
    )


async def cleanup(client, collection: str) -> int:
    """Delete every document this probe created. Returns the count."""
    deleted = 0
    for collection_id in (collection, f"{collection}_keys"):
        async for snapshot in client.collection(collection_id).stream():
            reference = client.collection(collection_id).document(snapshot.id)
            async for message in reference.collection("messages").stream():
                await reference.collection("messages").document(message.id).delete()
                deleted += 1
            await reference.delete()
            deleted += 1
    return deleted


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="GCP project id")
    parser.add_argument("--database", default="(default)", help="Firestore database id")
    args = parser.parse_args()

    try:
        from google.cloud.firestore import AsyncClient
    except ImportError:
        print(
            "error: google-cloud-firestore is not installed. Run "
            "`uv pip install '.[firestore]'` from agent_service/.",
            file=sys.stderr,
        )
        return 2

    # Throwaway collection: never the one a real deployment uses.
    collection = f"verify_{int(time.time())}_{secrets.token_hex(3)}"
    print(f"project={args.project} database={args.database} collection={collection}\n")

    def build_client():
        return AsyncClient(project=args.project, database=args.database)

    def repository_factory():
        return FirestoreConversationRepository(
            build_client(), collection=collection, retention_hours=24
        )

    results = Results()
    client = build_client()
    try:
        conversation_id = await verify(repository_factory, collection, results)
        await verify_ttl_field(client, collection, conversation_id, results)
    finally:
        deleted = await cleanup(client, collection)
        print(f"\ncleanup: deleted {deleted} document(s) from {collection}*")

    print()
    if results.failed:
        print(f"FAILED: {results.failed} of {len(results.checks)} checks did not pass")
        return 1
    print(f"OK: all {len(results.checks)} checks passed against live Firestore")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
