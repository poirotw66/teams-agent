"""Delivery outbox schema contracts and persistence models.

Formalizes the schema for the ``operational_delivery_outbox`` Firestore collection,
ensuring schema versioning, backward compatibility, and payload invariant validation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from operations_core.contracts import OperationalEvent

OUTBOX_SCHEMA_VERSION = 1
NEVER_WAKE = 1e30

DeliveryStatus = Literal["pending", "leased", "done", "conflict", "expired"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeliveryTargetState(StrictModel):
    """Lifecycle state of a delivery attempt to a single destination sink."""

    status: DeliveryStatus = "pending"
    attempts: int = Field(default=0, ge=0)
    next_attempt: float = 0.0
    lease_until: float = 0.0
    token: str | None = None
    last_error: str | None = None


class OutboxRecord(StrictModel):
    """Document schema for records stored in ``operational_delivery_outbox``."""

    schema_version: int = OUTBOX_SCHEMA_VERSION
    event: OperationalEvent | None = None
    fingerprint: str = Field(min_length=1)
    created_at: float
    expires_at: float
    deliveries: dict[str, DeliveryTargetState] = Field(default_factory=dict)
    wake_at: float = NEVER_WAKE

    def to_firestore_dict(self) -> dict[str, Any]:
        """Serialize record into Firestore document dictionary."""
        return {
            "schema_version": self.schema_version,
            "event": self.event.model_dump(mode="json") if self.event else None,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "deliveries": {
                target: state.model_dump(mode="python")
                for target, state in self.deliveries.items()
            },
            "wake_at": self.wake_at,
        }

    @classmethod
    def from_firestore_dict(cls, data: dict[str, Any]) -> OutboxRecord:
        """Construct OutboxRecord from raw Firestore document with backward compatibility."""
        payload = dict(data)
        schema_ver = payload.get("schema_version", OUTBOX_SCHEMA_VERSION)

        raw_event = payload.get("event")
        parsed_event: OperationalEvent | None = None
        if raw_event is not None:
            parsed_event = OperationalEvent.model_validate(raw_event)

        raw_deliveries = payload.get("deliveries", {})
        parsed_deliveries: dict[str, DeliveryTargetState] = {}
        for target, state_data in raw_deliveries.items():
            if isinstance(state_data, dict):
                known = {k: v for k, v in state_data.items() if k in DeliveryTargetState.model_fields}
                parsed_deliveries[target] = DeliveryTargetState(**known)

        return cls(
            schema_version=schema_ver,
            event=parsed_event,
            fingerprint=payload.get("fingerprint", ""),
            created_at=float(payload.get("created_at", 0.0)),
            expires_at=float(payload.get("expires_at", 0.0)),
            deliveries=parsed_deliveries,
            wake_at=float(payload.get("wake_at", NEVER_WAKE)),
        )


__all__ = [
    "NEVER_WAKE",
    "OUTBOX_SCHEMA_VERSION",
    "DeliveryStatus",
    "DeliveryTargetState",
    "OutboxRecord",
]
