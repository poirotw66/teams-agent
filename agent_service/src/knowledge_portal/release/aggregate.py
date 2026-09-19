"""Release domain aggregate protecting lifecycle invariants and state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from knowledge_portal.models import ReleaseRecord, utc_now

from .transitions import (
    ACTIVE,
    DEPLOYING,
    FAILED,
    GATE_BLOCKED,
    RELOAD_FAILED,
    ROLLED_BACK,
    can_promote,
    can_transition,
    ensure_can_transition,
    is_deactivatable,
    promote_rejection_message,
)


@dataclass(frozen=True)
class ReleaseAggregate:
    """Domain aggregate encapsulating ReleaseRecord state and transition invariants."""

    record: ReleaseRecord

    @classmethod
    def wrap(cls, record: ReleaseRecord) -> ReleaseAggregate:
        return cls(record=record)

    @property
    def release_id(self) -> str:
        return self.record.release_id

    @property
    def status(self) -> str:
        return self.record.status

    @property
    def is_promotable(self) -> bool:
        return can_promote(self.record.status)

    @property
    def is_deactivatable(self) -> bool:
        return is_deactivatable(self.record.status)

    def assert_promotable(self) -> None:
        """Enforce promotability invariant for candidate promotion."""
        if not self.is_promotable:
            raise ValueError(
                promote_rejection_message(
                    release_id=self.record.release_id,
                    status=self.record.status,
                )
            )

    def can_transition_to(self, target_status: str) -> bool:
        return can_transition(from_status=self.record.status, to_status=target_status)

    def transition_to(
        self,
        target_status: str,
        **updates: Any,
    ) -> ReleaseAggregate:
        """Enforce valid status hop invariant and return updated aggregate."""
        ensure_can_transition(
            from_status=self.record.status,
            to_status=target_status,
        )
        new_record = self.record.model_copy(
            update={
                "status": target_status,
                **updates,
            }
        )
        return ReleaseAggregate(record=new_record)

    def mark_deploying(self) -> ReleaseAggregate:
        return self.transition_to(
            DEPLOYING,
            failure_summary="",
        )

    def mark_active(self, *, activated_at: datetime | None = None) -> ReleaseAggregate:
        return self.transition_to(
            ACTIVE,
            failure_summary="",
            activated_at=activated_at or utc_now(),
        )

    def mark_failed(self, *, summary: str) -> ReleaseAggregate:
        return self.transition_to(
            FAILED,
            failure_summary=summary,
            activated_at=None,
        )

    def mark_gate_blocked(self, *, summary: str) -> ReleaseAggregate:
        return self.transition_to(
            GATE_BLOCKED,
            failure_summary=summary,
            activated_at=None,
        )

    def mark_reload_failed(self, *, summary: str) -> ReleaseAggregate:
        return self.transition_to(
            RELOAD_FAILED,
            failure_summary=summary,
            activated_at=None,
        )

    def mark_rolled_back(self) -> ReleaseAggregate:
        return self.transition_to(
            ROLLED_BACK,
        )
