from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from ..contracts import OperationalEvent

PRIMARY = "__primary__"
NEVER = 1e30


class DeliveryError(RuntimeError):
    """Safe error code only; never carry SDK responses, event bodies or credentials."""

    def __init__(self, code: str = "delivery_failed") -> None:
        allowed = {"delivery_failed", "sink_unavailable", "sink_rejected", "primary_missing",
                   "bigquery_sdk_failure", "bigquery_row_rejected"}
        self.code = code if code in allowed else "delivery_failed"
        super().__init__(self.code)


class EventConflict(DeliveryError):
    def __init__(self) -> None:
        super().__init__()
        self.code = "event_conflict"
        self.args = (self.code,)


def fingerprint(event: OperationalEvent) -> str:
    body = event.model_dump(mode="json")
    # Ingestion supplies these anew on retries. Freeze the FIRST accepted
    # values, but do not classify later ingestion clocks as fact conflicts.
    body.pop("ingested_at", None)
    body.pop("retention_expires_at", None)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def register(
    old: dict[str, Any] | None, event: OperationalEvent, sinks: list[str], now: float
) -> tuple[dict[str, Any], bool]:
    digest = fingerprint(event)
    if old is not None and old["fingerprint"] != digest:
        raise EventConflict()
    record = old or {
        "event": event.model_dump(mode="json"),
        "fingerprint": digest,
        "created_at": now,
        "expires_at": (event.retention_expires_at or (
            event.occurred_at + timedelta(days=365)
        )).timestamp(),
        "deliveries": {},
    }
    if record.get("event") is None:
        return record, False
    for target in [PRIMARY, *sinks]:
        record["deliveries"].setdefault(target, {
            "status": "pending", "attempts": 0, "next_attempt": now,
            "lease_until": 0.0, "token": None, "last_error": None,
        })
    update_wake(record)
    expired = expire_record(record, now)
    return record, old is None and not expired


def expire_record(record: dict[str, Any], now: float) -> bool:
    if record.get("event") is None or record["expires_at"] > now:
        return False
    record["event"] = None
    for state in record["deliveries"].values():
        state.update(status="expired", token=None, lease_until=0.0, last_error=None)
    record["wake_at"] = NEVER
    return True


def update_wake(record: dict[str, Any]) -> None:
    deliveries = record["deliveries"]
    available = deliveries if deliveries[PRIMARY]["status"] == "done" else {
        PRIMARY: deliveries[PRIMARY]
    }
    record["wake_at"] = min((
        state["lease_until"] if state["status"] == "leased" else state["next_attempt"]
        for state in available.values() if state["status"] in {"pending", "leased"}
    ), default=NEVER)


@dataclass(frozen=True)
class Lease:
    event: OperationalEvent
    target: str
    token: str
    attempts: int


def claim_record(
    record: dict[str, Any], targets: set[str], now: float, lease_seconds: float, limit: int
) -> list[Lease]:
    leases = []
    expire_record(record, now)
    if record.get("event") is None:
        return leases
    for target, state in record["deliveries"].items():
        if len(leases) >= limit:
            break
        if target not in targets or (
            target != PRIMARY and record["deliveries"][PRIMARY]["status"] != "done"
        ):
            continue
        due = state["next_attempt"] if state["status"] == "pending" else state["lease_until"]
        if state["status"] not in {"pending", "leased"} or due > now:
            continue
        token = str(uuid.uuid4())
        state.update(status="leased", token=token, lease_until=now + lease_seconds)
        state["attempts"] += 1
        leases.append(Lease(
            OperationalEvent.model_validate(record["event"]), target, token, state["attempts"]
        ))
    update_wake(record)
    return leases


def settle_record(
    record: dict[str, Any], lease: Lease, now: float, error: str | None, delay: float
) -> bool:
    state = record["deliveries"][lease.target]
    expire_record(record, now)
    if state["token"] != lease.token or state["status"] != "leased" or state["lease_until"] <= now:
        return False
    state.update(
        status="conflict" if error == "event_conflict" else "pending" if error else "done",
        token=None, lease_until=0.0, next_attempt=now + delay, last_error=error,
    )
    update_wake(record)
    return True


def summarize(records: list[dict[str, Any]], now: float) -> dict[str, Any]:
    targets: dict[str, dict[str, Any]] = {}
    for record in records:
        for target, state in record["deliveries"].items():
            counts = targets.setdefault(target, {
                "pending": 0, "leased": 0, "done": 0, "conflict": 0, "expired": 0,
                "attempts": 0, "oldest_pending_seconds": 0.0,
            })
            counts[state["status"]] += 1
            counts["attempts"] += state["attempts"]
            if state["status"] not in {"done", "expired"}:
                counts["oldest_pending_seconds"] = max(
                    counts["oldest_pending_seconds"], max(0, now - record["created_at"])
                )
    return {"events": len(records), "targets": targets}


class Journal(Protocol):
    async def put(self, event: OperationalEvent, sinks: list[str], now: float) -> bool: ...

    async def claim(
        self, targets: set[str], now: float, lease_seconds: float, limit: int,
        event_id: str | None = None,
    ) -> list[Lease]: ...

    async def settle(
        self, lease: Lease, now: float, error: str | None = None, delay: float = 0,
    ) -> bool: ...

    async def stats(self, now: float) -> dict[str, Any]: ...

    async def purge(self, now: float) -> int: ...
