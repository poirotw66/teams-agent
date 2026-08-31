"""Persistent HandoffRepository implementations for Phase 2."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .handoff import (
    ActiveHandoffCaseExistsError,
    HandoffCase,
    HandoffCaseNotFoundError,
    HandoffEvent,
    HandoffPermissionError,
    HandoffRepository,
    HandoffVersionConflictError,
    InMemoryHandoffRepository,
)
from .settings import RagSettings


def _active_id(tenant_id: str, conversation_id: str, requester_id: str) -> str:
    raw = f"{tenant_id}\0{conversation_id}\0{requester_id}".encode()
    return hashlib.sha256(raw).hexdigest()


class FileHandoffRepository(InMemoryHandoffRepository):
    """Single-process JSON repository that survives local restarts."""

    def __init__(self, path: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._path = path
        self._loaded = False
        self._file_lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._file_lock:
            if self._loaded:
                return
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._cases = {
                    item["caseId"]: HandoffCase.model_validate(item)
                    for item in data.get("cases", [])
                }
                self._active = {
                    self._active_key(case.tenantId, case.conversationId, case.requesterId): case.caseId
                    for case in self._cases.values()
                    if not case.is_terminal
                }
                self._events = {}
                for item in data.get("events", []):
                    event = HandoffEvent.model_validate(item)
                    self._events.setdefault(event.caseId, {})[event.eventId] = event
            self._loaded = True

    async def _persist(self) -> None:
        async with self._file_lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "cases": [case.model_dump(mode="json") for case in self._cases.values()],
                "events": [
                    event.model_dump(mode="json")
                    for events in self._events.values()
                    for event in events.values()
                ],
            }
            temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, self._path)

    async def create_case(self, case: HandoffCase) -> HandoffCase:
        await self._ensure_loaded()
        result = await super().create_case(case)
        await self._persist()
        return result

    async def get_case(self, case_id: str) -> HandoffCase | None:
        await self._ensure_loaded()
        result = await super().get_case(case_id)
        await self._persist()
        return result

    async def get_active_case(
        self, tenant_id: str, conversation_id: str, requester_id: str
    ) -> HandoffCase | None:
        await self._ensure_loaded()
        result = await super().get_active_case(
            tenant_id, conversation_id, requester_id
        )
        await self._persist()
        return result

    async def update_summary(self, case_id, summary, expected_version):
        await self._ensure_loaded()
        result = await super().update_summary(case_id, summary, expected_version)
        await self._persist()
        return result

    async def transition(self, case_id, from_status, to_status, expected_version):
        await self._ensure_loaded()
        result = await super().transition(
            case_id, from_status, to_status, expected_version
        )
        await self._persist()
        return result

    async def close_case(self, case_id, requester_id, expected_version):
        await self._ensure_loaded()
        result = await super().close_case(case_id, requester_id, expected_version)
        await self._persist()
        return result

    async def append_event(self, event: HandoffEvent) -> None:
        await self._ensure_loaded()
        await super().append_event(event)
        await self._persist()

    async def list_events(self, case_id: str) -> list[HandoffEvent]:
        await self._ensure_loaded()
        return await super().list_events(case_id)

    async def expire_due_cases(self) -> list[HandoffCase]:
        await self._ensure_loaded()
        result = await super().expire_due_cases()
        await self._persist()
        return result


class FirestoreHandoffRepository:
    """Firestore repository using transactions for uniqueness and OCC.

    Cases, active-conversation indexes, and audit events use separate root
    collections. Case/event documents carry ``retentionExpiresAt`` for TTL;
    the active index is deleted when the case becomes terminal.
    """

    def __init__(self, client: Any, collection: str = "handoffs") -> None:
        self._client = client
        self._cases = client.collection(collection)
        self._active = client.collection(f"{collection}_active")
        self._events = client.collection(f"{collection}_events")

    @staticmethod
    def _case(snapshot: Any) -> HandoffCase | None:
        return HandoffCase.model_validate(snapshot.to_dict()) if snapshot.exists else None

    async def create_case(self, case: HandoffCase) -> HandoffCase:
        case_ref = self._cases.document(case.caseId)
        active_ref = self._active.document(
            _active_id(case.tenantId, case.conversationId, case.requesterId)
        )
        transaction = self._client.transaction()

        async def operation(transaction):
            existing = await case_ref.get(transaction=transaction)
            if existing.exists:
                stored = self._case(existing)
                if stored == case:
                    return stored
                raise HandoffVersionConflictError(case.caseId)
            active = await active_ref.get(transaction=transaction)
            if active.exists:
                raise ActiveHandoffCaseExistsError(active.to_dict().get("caseId", ""))
            transaction.set(case_ref, case.model_dump(mode="python"))
            if not case.is_terminal:
                transaction.set(active_ref, {"caseId": case.caseId})
            return case

        return await self._run_transaction(transaction, operation)

    async def get_case(self, case_id: str) -> HandoffCase | None:
        return self._case(await self._cases.document(case_id).get())

    async def get_active_case(self, tenant_id, conversation_id, requester_id):
        from .handoff import ActorType, HandoffEvent, HandoffStatus, utc_now

        active = await self._active.document(
            _active_id(tenant_id, conversation_id, requester_id)
        ).get()
        if not active.exists:
            return None
        case = await self.get_case(active.to_dict()["caseId"])
        if case is None or case.is_terminal or case.requesterId != requester_id:
            return None
        if case.sessionExpiresAt is not None and case.sessionExpiresAt <= utc_now():
            try:
                expired = await self.transition(
                    case.caseId, case.status, HandoffStatus.EXPIRED, case.version
                )
                await self.append_event(
                    HandoffEvent(
                        eventId=f"expire-{case.caseId}-{expired.version}",
                        caseId=case.caseId,
                        eventType="handoff.expired",
                        actorType=ActorType.SYSTEM,
                        occurredAt=utc_now(),
                        payload={"fromStatus": case.status, "toStatus": "EXPIRED"},
                        correlationId=case.correlationId,
                        retentionExpiresAt=case.retentionExpiresAt,
                    )
                )
            except HandoffVersionConflictError:
                pass
            return None
        return case

    async def _mutate(self, case_id: str, expected_version: int, mutator):
        ref = self._cases.document(case_id)
        transaction = self._client.transaction()

        async def operation(transaction):
            case = self._case(await ref.get(transaction=transaction))
            if case is None:
                raise HandoffCaseNotFoundError(case_id)
            if case.version != expected_version:
                raise HandoffVersionConflictError(case_id)
            updated = mutator(case)
            transaction.set(ref, updated.model_dump(mode="python"))
            if updated.is_terminal:
                transaction.delete(
                    self._active.document(
                        _active_id(case.tenantId, case.conversationId, case.requesterId)
                    )
                )
            return updated

        return await self._run_transaction(transaction, operation)

    async def update_summary(self, case_id, summary, expected_version):
        from .handoff import HandoffStatus, InvalidHandoffTransitionError, utc_now

        def mutate(case):
            if case.status not in {
                HandoffStatus.OFFERED,
                HandoffStatus.SUMMARY_REVIEW,
                HandoffStatus.AWAITING_SUPPLEMENT,
            }:
                raise InvalidHandoffTransitionError("summary cannot be updated")
            return case.model_copy(
                update={"summary": summary, "updatedAt": utc_now(), "version": case.version + 1}
            )

        return await self._mutate(case_id, expected_version, mutate)

    async def transition(self, case_id, from_status, to_status, expected_version):
        from .handoff import TERMINAL_STATUSES, InvalidHandoffTransitionError, utc_now

        def mutate(case):
            if case.status != from_status:
                raise InvalidHandoffTransitionError("stale handoff status")
            allowed = {
                "OFFERED": {"SUMMARY_REVIEW", "CANCELLED", "FAILED", "EXPIRED"},
                "SUMMARY_REVIEW": {
                    "AWAITING_SUPPLEMENT",
                    "DEMO_ACTIVE",
                    "CANCELLED",
                    "FAILED",
                    "EXPIRED",
                    "ROUTED_TO_TICKET",
                },
                "AWAITING_SUPPLEMENT": {
                    "SUMMARY_REVIEW",
                    "DEMO_ACTIVE",
                    "CANCELLED",
                    "FAILED",
                    "EXPIRED",
                    "ROUTED_TO_TICKET",
                },
                "DEMO_ACTIVE": {"CLOSED", "FAILED", "EXPIRED", "ROUTED_TO_TICKET"},
            }
            if to_status.value not in allowed.get(from_status.value, set()):
                raise InvalidHandoffTransitionError("invalid handoff transition")
            now = utc_now()
            return case.model_copy(update={
                "status": to_status,
                "updatedAt": now,
                "closedAt": now if to_status in TERMINAL_STATUSES else None,
                "version": case.version + 1,
            })

        return await self._mutate(case_id, expected_version, mutate)

    async def close_case(self, case_id, requester_id, expected_version):
        from .handoff import HandoffStatus, InvalidHandoffTransitionError, utc_now

        current = await self.get_case(case_id)
        if current is None:
            raise HandoffCaseNotFoundError(case_id)
        if current.requesterId != requester_id:
            raise HandoffPermissionError(case_id)
        if current.status == HandoffStatus.CLOSED:
            return current

        def mutate(case):
            if case.requesterId != requester_id:
                raise HandoffPermissionError(case_id)
            if case.status != HandoffStatus.DEMO_ACTIVE:
                raise InvalidHandoffTransitionError("case is not DEMO_ACTIVE")
            now = utc_now()
            return case.model_copy(update={
                "status": HandoffStatus.CLOSED,
                "updatedAt": now,
                "closedAt": now,
                "version": case.version + 1,
            })

        return await self._mutate(case_id, expected_version, mutate)

    async def append_event(self, event: HandoffEvent) -> None:
        ref = self._events.document(event.eventId)
        snapshot = await ref.get()
        if snapshot.exists:
            if HandoffEvent.model_validate(snapshot.to_dict()) != event:
                raise HandoffVersionConflictError(event.eventId)
            return
        await ref.set(event.model_dump(mode="python"))

    async def list_events(self, case_id: str) -> list[HandoffEvent]:
        query = self._events.where("caseId", "==", case_id).order_by("occurredAt")
        return [HandoffEvent.model_validate(item.to_dict()) async for item in query.stream()]

    async def expire_due_cases(self) -> list[HandoffCase]:
        from .handoff import ActorType, HandoffEvent, HandoffStatus, utc_now

        query = self._cases.where("sessionExpiresAt", "<=", utc_now())
        expired = []
        async for snapshot in query.stream():
            case = self._case(snapshot)
            if case is None or case.is_terminal:
                continue
            try:
                updated = await self.transition(
                    case.caseId, case.status, HandoffStatus.EXPIRED, case.version
                )
                await self.append_event(
                    HandoffEvent(
                        eventId=f"expire-{case.caseId}-{updated.version}",
                        caseId=case.caseId,
                        eventType="handoff.expired",
                        actorType=ActorType.SYSTEM,
                        occurredAt=utc_now(),
                        payload={"fromStatus": case.status, "toStatus": "EXPIRED"},
                        correlationId=case.correlationId,
                        retentionExpiresAt=case.retentionExpiresAt,
                    )
                )
                expired.append(updated)
            except HandoffVersionConflictError:
                continue
        return expired

    @staticmethod
    async def _run_transaction(transaction: Any, operation: Any):
        try:
            from google.cloud.firestore_v1.async_transaction import async_transactional
        except ImportError as error:  # pragma: no cover - guarded by optional extra
            raise RuntimeError("FIRESTORE mode requires the firestore extra") from error
        return await async_transactional(operation)(transaction)


def build_handoff_repository(
    settings: RagSettings, firestore_client: Any | None = None
) -> HandoffRepository:
    mode = settings.handoff_repository_mode
    if mode == "MEMORY":
        return InMemoryHandoffRepository()
    if mode == "FILE":
        path = settings.handoff_store_path or settings.data_dir / "handoffs" / "handoffs.json"
        if path.suffix.lower() != ".json":
            path = path / "handoffs.json"
        return FileHandoffRepository(path)
    if firestore_client is None:
        try:
            from google.cloud import firestore
        except ImportError as error:  # pragma: no cover - optional production dependency
            raise RuntimeError("FIRESTORE mode requires the firestore extra") from error
        kwargs = {}
        if settings.handoff_firestore_project:
            kwargs["project"] = settings.handoff_firestore_project
        if settings.handoff_firestore_database:
            kwargs["database"] = settings.handoff_firestore_database
        firestore_client = firestore.AsyncClient(**kwargs)
    return FirestoreHandoffRepository(
        firestore_client, settings.handoff_firestore_collection
    )
