"""Human handoff domain and storage contract (Phase 2 spec sections 8-10)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HandoffStatus(StrEnum):
    OFFERED = "OFFERED"
    SUMMARY_REVIEW = "SUMMARY_REVIEW"
    DEMO_ACTIVE = "DEMO_ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    ROUTED_TO_TICKET = "ROUTED_TO_TICKET"


class ActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"


TERMINAL_STATUSES = frozenset(
    {
        HandoffStatus.CLOSED,
        HandoffStatus.CANCELLED,
        HandoffStatus.FAILED,
        HandoffStatus.EXPIRED,
        HandoffStatus.ROUTED_TO_TICKET,
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class CaseSummary(_StrictModel):
    issue: str = Field(min_length=1)
    userNeed: str = Field(min_length=1)
    conversationHighlights: list[str] = Field(default_factory=list)
    attemptedSolutions: list[str] = Field(default_factory=list)
    unresolvedReason: str = Field(min_length=1)
    requestedOutcome: str = Field(min_length=1)
    generatedAt: datetime
    confirmedAt: datetime | None = None
    confirmedBy: str | None = None
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _confirmation_is_complete(self) -> CaseSummary:
        _aware(self.generatedAt, "generatedAt")
        if self.confirmedAt is not None:
            _aware(self.confirmedAt, "confirmedAt")
        if (self.confirmedAt is None) != (self.confirmedBy is None):
            raise ValueError("confirmedAt and confirmedBy must be set together")
        return self


class HandoffCase(_StrictModel):
    caseId: str = Field(min_length=1)
    sessionId: str = Field(min_length=1)
    tenantId: str = Field(min_length=1)
    conversationId: str = Field(min_length=1)
    requesterId: str = Field(min_length=1)
    requesterName: str | None = None
    status: HandoffStatus
    providerMode: str = "DEMO"
    summary: CaseSummary
    createdAt: datetime
    updatedAt: datetime
    closedAt: datetime | None = None
    sessionExpiresAt: datetime | None = None
    retentionExpiresAt: datetime | None = None
    version: int = Field(default=1, ge=1)
    correlationId: str = Field(min_length=1)

    @field_validator("providerMode")
    @classmethod
    def _demo_only(cls, value: str) -> str:
        if value != "DEMO":
            raise ValueError("providerMode must be DEMO in Phase 2")
        return value

    @model_validator(mode="after")
    def _timestamps_are_consistent(self) -> HandoffCase:
        for name in (
            "createdAt",
            "updatedAt",
            "closedAt",
            "sessionExpiresAt",
            "retentionExpiresAt",
        ):
            value = getattr(self, name)
            if value is not None:
                _aware(value, name)
        if self.updatedAt < self.createdAt:
            raise ValueError("updatedAt must not precede createdAt")
        if self.status in TERMINAL_STATUSES and self.closedAt is None:
            raise ValueError("terminal cases require closedAt")
        if self.status not in TERMINAL_STATUSES and self.closedAt is not None:
            raise ValueError("non-terminal cases cannot have closedAt")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class HandoffEvent(_StrictModel):
    eventId: str = Field(min_length=1)
    caseId: str = Field(min_length=1)
    eventType: str = Field(min_length=1)
    actorType: ActorType
    actorId: str | None = None
    occurredAt: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    correlationId: str = Field(min_length=1)
    retentionExpiresAt: datetime | None = None

    @model_validator(mode="after")
    def _validate_event(self) -> HandoffEvent:
        _aware(self.occurredAt, "occurredAt")
        if self.retentionExpiresAt is not None:
            _aware(self.retentionExpiresAt, "retentionExpiresAt")
        return self


class HandoffRepositoryError(RuntimeError):
    pass


class HandoffCaseNotFoundError(HandoffRepositoryError):
    pass


class ActiveHandoffCaseExistsError(HandoffRepositoryError):
    pass


class HandoffVersionConflictError(HandoffRepositoryError):
    pass


class InvalidHandoffTransitionError(HandoffRepositoryError):
    pass


class HandoffPermissionError(HandoffRepositoryError):
    pass


class HandoffRepository(Protocol):
    async def create_case(self, case: HandoffCase) -> HandoffCase: ...

    async def get_case(self, case_id: str) -> HandoffCase | None: ...

    async def get_active_case(
        self, tenant_id: str, conversation_id: str, requester_id: str
    ) -> HandoffCase | None: ...

    async def update_summary(
        self, case_id: str, summary: CaseSummary, expected_version: int
    ) -> HandoffCase: ...

    async def transition(
        self,
        case_id: str,
        from_status: HandoffStatus,
        to_status: HandoffStatus,
        expected_version: int,
    ) -> HandoffCase: ...

    async def close_case(
        self, case_id: str, requester_id: str, expected_version: int
    ) -> HandoffCase: ...

    async def append_event(self, event: HandoffEvent) -> None: ...

    async def list_events(self, case_id: str) -> list[HandoffEvent]: ...

    async def expire_due_cases(self) -> list[HandoffCase]: ...


class InMemoryHandoffRepository:
    """Concurrency-safe fake and local MEMORY implementation.

    Active uniqueness uses tenant + Teams conversation + requester so channel
    members do not block each other's handoff cases.
    """

    def __init__(self, clock: Clock = utc_now) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._cases: dict[str, HandoffCase] = {}
        self._active: dict[str, str] = {}
        self._events: dict[str, dict[str, HandoffEvent]] = {}

    @staticmethod
    def _active_key(tenant_id: str, conversation_id: str, requester_id: str) -> str:
        return f"{tenant_id}::{conversation_id}::{requester_id}"

    def _copy(self, case: HandoffCase) -> HandoffCase:
        return case.model_copy(deep=True)

    def _check_version(self, case: HandoffCase, expected: int) -> None:
        if case.version != expected:
            raise HandoffVersionConflictError(
                f"case {case.caseId!r} version is {case.version}, expected {expected}"
            )

    def _expire_locked(self, case: HandoffCase) -> HandoffCase:
        now = self._clock()
        if (
            case.status not in TERMINAL_STATUSES
            and case.sessionExpiresAt is not None
            and case.sessionExpiresAt <= now
        ):
            expired = case.model_copy(
                update={
                    "status": HandoffStatus.EXPIRED,
                    "updatedAt": now,
                    "closedAt": now,
                    "version": case.version + 1,
                }
            )
            self._cases[case.caseId] = expired
            self._active.pop(
                self._active_key(case.tenantId, case.conversationId, case.requesterId),
                None,
            )
            event = HandoffEvent(
                eventId=str(uuid.uuid4()),
                caseId=case.caseId,
                eventType="handoff.expired",
                actorType=ActorType.SYSTEM,
                occurredAt=now,
                payload={"fromStatus": case.status, "toStatus": HandoffStatus.EXPIRED},
                correlationId=case.correlationId,
                retentionExpiresAt=case.retentionExpiresAt,
            )
            self._events.setdefault(case.caseId, {})[event.eventId] = event
            return expired
        return case

    async def create_case(self, case: HandoffCase) -> HandoffCase:
        key = self._active_key(case.tenantId, case.conversationId, case.requesterId)
        async with self._lock:
            same = self._cases.get(case.caseId)
            if same is not None:
                if same == case:
                    return self._copy(same)
                raise HandoffVersionConflictError(f"caseId {case.caseId!r} already exists")
            active_id = self._active.get(key)
            if active_id is not None:
                active = self._expire_locked(self._cases[active_id])
                if not active.is_terminal:
                    raise ActiveHandoffCaseExistsError(
                        f"conversation already has active case {active.caseId!r}"
                    )
            stored = self._copy(case)
            self._cases[case.caseId] = stored
            if not stored.is_terminal:
                self._active[key] = stored.caseId
            return self._copy(stored)

    async def get_case(self, case_id: str) -> HandoffCase | None:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                return None
            return self._copy(self._expire_locked(case))

    async def get_active_case(
        self, tenant_id: str, conversation_id: str, requester_id: str
    ) -> HandoffCase | None:
        async with self._lock:
            case_id = self._active.get(
                self._active_key(tenant_id, conversation_id, requester_id)
            )
            if case_id is None:
                return None
            case = self._expire_locked(self._cases[case_id])
            if case.is_terminal or case.requesterId != requester_id:
                return None
            return self._copy(case)

    async def update_summary(
        self, case_id: str, summary: CaseSummary, expected_version: int
    ) -> HandoffCase:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HandoffCaseNotFoundError(case_id)
            case = self._expire_locked(case)
            self._check_version(case, expected_version)
            if case.status not in {
                HandoffStatus.OFFERED,
                HandoffStatus.SUMMARY_REVIEW,
            }:
                raise InvalidHandoffTransitionError(
                    "summary can only be updated before handoff activation"
                )
            updated = case.model_copy(
                update={
                    "summary": summary.model_copy(deep=True),
                    "updatedAt": self._clock(),
                    "version": case.version + 1,
                }
            )
            self._cases[case_id] = updated
            return self._copy(updated)

    async def transition(
        self,
        case_id: str,
        from_status: HandoffStatus,
        to_status: HandoffStatus,
        expected_version: int,
    ) -> HandoffCase:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HandoffCaseNotFoundError(case_id)
            case = self._expire_locked(case)
            self._check_version(case, expected_version)
            if case.status != from_status:
                raise InvalidHandoffTransitionError(
                    f"case status is {case.status}, expected {from_status}"
                )
            allowed = {
                HandoffStatus.OFFERED: {
                    HandoffStatus.SUMMARY_REVIEW,
                    HandoffStatus.CANCELLED,
                    HandoffStatus.FAILED,
                    HandoffStatus.EXPIRED,
                },
                HandoffStatus.SUMMARY_REVIEW: {
                    HandoffStatus.DEMO_ACTIVE,
                    HandoffStatus.CANCELLED,
                    HandoffStatus.FAILED,
                    HandoffStatus.EXPIRED,
                    HandoffStatus.ROUTED_TO_TICKET,
                },
                HandoffStatus.DEMO_ACTIVE: {
                    HandoffStatus.CLOSED,
                    HandoffStatus.FAILED,
                    HandoffStatus.EXPIRED,
                    HandoffStatus.ROUTED_TO_TICKET,
                },
            }
            if to_status not in allowed.get(from_status, set()):
                raise InvalidHandoffTransitionError(
                    f"transition {from_status} -> {to_status} is not allowed"
                )
            now = self._clock()
            updated = case.model_copy(
                update={
                    "status": to_status,
                    "updatedAt": now,
                    "closedAt": now if to_status in TERMINAL_STATUSES else None,
                    "version": case.version + 1,
                }
            )
            self._cases[case_id] = updated
            key = self._active_key(case.tenantId, case.conversationId, case.requesterId)
            if updated.is_terminal:
                self._active.pop(key, None)
            else:
                self._active[key] = case_id
            return self._copy(updated)

    async def close_case(
        self, case_id: str, requester_id: str, expected_version: int
    ) -> HandoffCase:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HandoffCaseNotFoundError(case_id)
            case = self._expire_locked(case)
            if case.requesterId != requester_id:
                raise HandoffPermissionError("only the original requester may close the case")
            if case.status == HandoffStatus.CLOSED:
                return self._copy(case)
            self._check_version(case, expected_version)
            if case.status != HandoffStatus.DEMO_ACTIVE:
                raise InvalidHandoffTransitionError("only DEMO_ACTIVE cases may be closed")
            now = self._clock()
            closed = case.model_copy(
                update={
                    "status": HandoffStatus.CLOSED,
                    "updatedAt": now,
                    "closedAt": now,
                    "version": case.version + 1,
                }
            )
            self._cases[case_id] = closed
            self._active.pop(
                self._active_key(case.tenantId, case.conversationId, case.requesterId),
                None,
            )
            return self._copy(closed)

    async def append_event(self, event: HandoffEvent) -> None:
        async with self._lock:
            if event.caseId not in self._cases:
                raise HandoffCaseNotFoundError(event.caseId)
            events = self._events.setdefault(event.caseId, {})
            current = events.get(event.eventId)
            if current is not None and current != event:
                raise HandoffVersionConflictError(f"eventId {event.eventId!r} already exists")
            events[event.eventId] = event.model_copy(deep=True)

    async def list_events(self, case_id: str) -> list[HandoffEvent]:
        async with self._lock:
            events = self._events.get(case_id, {})
            return [
                event.model_copy(deep=True)
                for event in sorted(events.values(), key=lambda item: (item.occurredAt, item.eventId))
            ]

    async def expire_due_cases(self) -> list[HandoffCase]:
        async with self._lock:
            expired: list[HandoffCase] = []
            for case in list(self._cases.values()):
                updated = self._expire_locked(case)
                if updated.status == HandoffStatus.EXPIRED and case.status != updated.status:
                    expired.append(self._copy(updated))
            return expired
