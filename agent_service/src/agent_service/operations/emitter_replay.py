"""Local replay fingerprint store for operational event emission."""

from __future__ import annotations

from .contracts import OperationalEvent
from .emitter_exceptions import (
    OperationalEventReplayConflict,
    OperationalEventReplayDuplicate,
)
from .event_identity import event_fingerprint


class ReplayFingerprintStore:
    """Process-local conflict detection for immutable operational facts.

    Persistent compare-and-create belongs to the delivery/store integration;
    no old payload is substituted here.
    """

    def __init__(self) -> None:
        self.request_fingerprints: dict[str, str] = {}
        self.event_fingerprints: dict[str, str] = {}
        self.call_manifests: dict[str, set[str]] = {}
        self.final_usage: dict[str, str] = {}

    def assert_immutable(
        self,
        request_key: str,
        request_fact: object,
        events: list[OperationalEvent],
        *,
        call_ids: set[str] | None = None,
        usage_fact: object = None,
        final_usage: bool = False,
    ) -> None:
        request_hash = event_fingerprint(request_fact)
        if self.request_fingerprints.get(request_key, request_hash) != request_hash:
            raise OperationalEventReplayConflict("logical request replay changed immutable facts")
        if final_usage and request_key in self.final_usage:
            raise OperationalEventReplayDuplicate
        proposed: dict[str, str] = {}
        for event in events:
            fingerprint = event_fingerprint(event)
            if event.event_id in proposed:
                raise OperationalEventReplayConflict("duplicate event identity within emission")
            if self.event_fingerprints.get(event.event_id, fingerprint) != fingerprint:
                raise OperationalEventReplayConflict("event replay changed immutable payload")
            proposed[event.event_id] = fingerprint
        usage_hash = event_fingerprint(usage_fact)
        if call_ids is not None:
            if not self.call_manifests.get(request_key, set()).issubset(call_ids):
                raise OperationalEventReplayConflict("replay removed collector facts")
            if self.final_usage.get(request_key, usage_hash) != usage_hash:
                raise OperationalEventReplayConflict("replay changed finalized usage")
        # Commit only after the entire batch validates; a rejected build cannot
        # poison future retries or register half a batch.
        self.request_fingerprints[request_key] = request_hash
        self.event_fingerprints.update(proposed)
        if call_ids is not None:
            self.call_manifests[request_key] = call_ids
        if final_usage:
            self.final_usage[request_key] = usage_hash

    def clear_final_usage(self, request_key: str) -> None:
        self.final_usage.pop(request_key, None)
