from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time
from collections.abc import Callable
from typing import Any

from .journal import PRIMARY, DeliveryError, EventConflict, Journal, Lease, fingerprint

logger = logging.getLogger(__name__)


class DeliveryWorker:
    def __init__(
        self, journal: Journal, primary: Any, sinks: dict[str, Any], *,
        lease_seconds: float = 30, timeout_seconds: float = 20,
        retry_base_seconds: float = 1, retry_max_seconds: float = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if timeout_seconds >= lease_seconds:
            raise ValueError("delivery_timeout_must_be_shorter_than_lease")
        if min(timeout_seconds, lease_seconds, retry_base_seconds, retry_max_seconds) <= 0:
            raise ValueError("delivery_intervals_must_be_positive")
        self.journal = journal
        self.primary = primary
        self.sinks = sinks
        self.lease_seconds = lease_seconds
        self.timeout_seconds = timeout_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.clock = clock

    async def _existing_primary(self, event_id: str) -> Any | None:
        cursor = None
        while True:
            events, cursor = await self.primary.list_events(limit=250, cursor=cursor)
            for event in events:
                if event.event_id == event_id:
                    return event
            if cursor is None:
                return None

    async def _write(self, lease: Lease) -> None:
            if lease.target == PRIMARY:
                inserted = await self.primary.append(lease.event)
                if not inserted:
                    existing = await self._existing_primary(lease.event.event_id)
                    if existing is None:
                        raise DeliveryError("primary_missing")
                    if fingerprint(existing) != fingerprint(lease.event):
                        raise EventConflict()
            else:
                sink = self.sinks.get(lease.target)
                if sink is None:
                    raise DeliveryError("sink_unavailable")
                await sink.append(lease.event)

    async def _deliver(self, lease: Lease) -> None:
        error = None
        try:
            await asyncio.wait_for(self._write(lease), timeout=self.timeout_seconds)
        except asyncio.CancelledError:
            raise  # Unacknowledged lease is recovered after expiry on restart.
        except EventConflict:
            error = "event_conflict"
        except DeliveryError as exc:
            error = exc.code
        except Exception:  # SDK payloads and raw exceptions never enter the journal or log.
            error = "delivery_failed"
        delay = 0 if error is None or error == "event_conflict" else min(
            self.retry_max_seconds, self.retry_base_seconds * (2 ** min(lease.attempts - 1, 30))
        )
        settled = await self.journal.settle(lease, self.clock(), error, delay)
        if not settled:
            logger.warning("Delivery lease expired target=%s", lease.target)

    async def run_once(
        self, *, limit: int = 100, event_id: str | None = None,
        targets: set[str] | None = None,
    ) -> int:
        active = targets or {PRIMARY, *self.sinks}
        leases = await self.journal.claim(
            active, self.clock(), self.lease_seconds, limit, event_id
        )
        await asyncio.gather(*(self._deliver(lease) for lease in leases))
        return len(leases)

    async def deliver_event(self, event_id: str, *, include_sinks: bool) -> int:
        targets = {PRIMARY, *self.sinks} if include_sinks else {PRIMARY}
        delivered = 0
        # Primary completion unlocks sinks, so a successful inline full delivery
        # needs at most two claim rounds.
        for _ in range(2):
            count = await self.run_once(event_id=event_id, targets=targets)
            delivered += count
            if count == 0:
                break
        return delivered

    async def reconcile_primary(self, *, page_size: int = 250) -> int:
        cursor = None
        registered = 0
        while True:
            events, cursor = await self.primary.list_events(limit=page_size, cursor=cursor)
            for event in events:
                if await self.journal.put(event, list(self.sinks), self.clock()):
                    registered += 1
            if cursor is None:
                return registered

    async def run_forever(self, *, poll_seconds: float, batch_size: int) -> None:
        stopping = asyncio.Event()
        loop = asyncio.get_running_loop()
        for name in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(name, stopping.set)
            except NotImplementedError:  # pragma: no cover - Windows
                pass
        while not stopping.is_set():
            processed = await self.run_once(limit=batch_size)
            if processed == 0:
                try:
                    await asyncio.wait_for(stopping.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Drain the operational event delivery outbox")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args()
    from ..runtime import build_ops_runtime

    runtime = build_ops_runtime()
    if runtime is None or runtime.delivery_worker is None:
        raise RuntimeError("durable_delivery_is_not_configured")
    if args.reconcile:
        await runtime.delivery_worker.reconcile_primary()
    if args.once:
        while await runtime.delivery_worker.run_once(limit=runtime.settings.delivery_batch_size):
            pass
    else:
        await runtime.delivery_worker.run_forever(
            poll_seconds=runtime.settings.delivery_poll_seconds,
            batch_size=runtime.settings.delivery_batch_size,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a deployment process
    raise SystemExit(asyncio.run(_main()))
