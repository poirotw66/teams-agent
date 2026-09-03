from __future__ import annotations

from typing import Protocol

from .models import FaqAuditEvent


class FaqAuditDeliveryPort(Protocol):
    """Host-owned bridge to the Phase 0 AuditStore.

    The FAQ repository's audit is the transactional source of truth. A host
    dispatcher must deliver this event after commit, keyed by ``audit_id`` so
    retries are idempotent; it must not turn a completed FAQ write into a
    failure merely because a separately stored global audit projection is late.
    """

    def deliver(self, event: FaqAuditEvent) -> None: ...
