"""Quality gate repository port and in-memory implementation.

File and Firestore adapters live in dedicated modules and are re-exported here
so existing ``from .gate_repository import ...`` imports keep working.
"""

from __future__ import annotations

import threading
from typing import Protocol

from .errors import EvaluationVersionConflictError
from .gate_models import (
    ActivationAuditRecord,
    ActiveReleasePointer,
    BreakGlassRequest,
    EvalSchedule,
    GateDecision,
    GateException,
    GatePolicy,
    GatePolicyVersion,
    QualityCaseLink,
    ScheduleDispatchResult,
)


class QualityGateRepositoryProtocol(Protocol):
    def save_policy(self, policy: GatePolicy, expected_version: int | None = None) -> None: ...

    def get_policy(self, policy_id: str) -> GatePolicy | None: ...

    def list_policies(self, tenant_id: str | None = None) -> list[GatePolicy]: ...

    def save_version(
        self, version: GatePolicyVersion, expected_etag: int | None = None
    ) -> None: ...

    def get_version(self, policy_id: str, version: int) -> GatePolicyVersion | None: ...

    def list_versions(self, policy_id: str) -> list[GatePolicyVersion]: ...

    def save_decision(self, decision: GateDecision) -> None: ...

    def get_decision(self, decision_id: str) -> GateDecision | None: ...

    def list_decisions(
        self, target_manifest_hash: str | None = None, tenant_id: str | None = None
    ) -> list[GateDecision]: ...

    def save_exception(self, exception: GateException) -> None: ...

    def get_exception(self, exception_id: str) -> GateException | None: ...

    def save_schedule(
        self, schedule: EvalSchedule, expected_revision: int | None = None
    ) -> None: ...

    def get_schedule(self, schedule_id: str) -> EvalSchedule | None: ...

    def list_schedules(self, tenant_id: str | None = None) -> list[EvalSchedule]: ...

    def save_quality_case(self, link: QualityCaseLink) -> None: ...

    def get_quality_case(self, quality_case_id: str) -> QualityCaseLink | None: ...

    def get_quality_case_by_execution(self, execution_id: str) -> QualityCaseLink | None: ...

    def save_active_pointer(
        self, pointer: ActiveReleasePointer, expected_etag: int | None = None
    ) -> None: ...

    def get_active_pointer(
        self, tenant_id: str, environment: str, target_type: str
    ) -> ActiveReleasePointer | None: ...

    def list_active_pointers(self, tenant_id: str | None = None) -> list[ActiveReleasePointer]: ...

    def save_break_glass(self, bg: BreakGlassRequest) -> None: ...

    def get_break_glass(self, break_glass_id: str) -> BreakGlassRequest | None: ...

    def save_activation_audit(self, audit: ActivationAuditRecord) -> None: ...

    def list_activation_audits(
        self, tenant_id: str | None = None
    ) -> list[ActivationAuditRecord]: ...

    def save_schedule_dispatch(self, dispatch: ScheduleDispatchResult) -> bool: ...

    def get_schedule_dispatch(self, logical_key: str) -> ScheduleDispatchResult | None: ...


class InMemoryQualityGateRepository:
    """Thread-safe in-memory store for gate policies, versions, decisions, exceptions, and schedules."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._policies: dict[str, GatePolicy] = {}
        self._versions: dict[tuple[str, int], GatePolicyVersion] = {}
        self._decisions: dict[str, GateDecision] = {}
        self._exceptions: dict[str, GateException] = {}
        self._schedules: dict[str, EvalSchedule] = {}
        self._quality_cases: dict[str, QualityCaseLink] = {}
        self._pointers: dict[tuple[str, str, str], ActiveReleasePointer] = {}
        self._break_glasses: dict[str, BreakGlassRequest] = {}
        self._activation_audits: list[ActivationAuditRecord] = []
        self._dispatches: dict[str, ScheduleDispatchResult] = {}

    def save_policy(self, policy: GatePolicy, expected_version: int | None = None) -> None:
        with self._lock:
            existing = self._policies.get(policy.policy_id)
            if expected_version is not None and existing:
                if existing.current_version != expected_version:
                    raise EvaluationVersionConflictError(
                        f"Policy {policy.policy_id} version mismatch: expected {expected_version}, got {existing.current_version}"
                    )
            self._policies[policy.policy_id] = policy

    def get_policy(self, policy_id: str) -> GatePolicy | None:
        with self._lock:
            return self._policies.get(policy_id)

    def list_policies(self, tenant_id: str | None = None) -> list[GatePolicy]:
        with self._lock:
            if tenant_id:
                return [p for p in self._policies.values() if p.tenant_id == tenant_id]
            return list(self._policies.values())

    def save_version(self, version: GatePolicyVersion, expected_etag: int | None = None) -> None:
        with self._lock:
            key = (version.policy_id, version.version)
            existing = self._versions.get(key)
            if expected_etag is not None and existing:
                if existing.etag != expected_etag:
                    raise EvaluationVersionConflictError(
                        f"PolicyVersion {key} etag mismatch: expected {expected_etag}, got {existing.etag}"
                    )
            self._versions[key] = version

    def get_version(self, policy_id: str, version: int) -> GatePolicyVersion | None:
        with self._lock:
            return self._versions.get((policy_id, version))

    def list_versions(self, policy_id: str) -> list[GatePolicyVersion]:
        with self._lock:
            return [v for (pid, _), v in self._versions.items() if pid == policy_id]

    def save_decision(self, decision: GateDecision) -> None:
        with self._lock:
            self._decisions[decision.decision_id] = decision

    def get_decision(self, decision_id: str) -> GateDecision | None:
        with self._lock:
            return self._decisions.get(decision_id)

    def list_decisions(
        self, target_manifest_hash: str | None = None, tenant_id: str | None = None
    ) -> list[GateDecision]:
        with self._lock:
            results = list(self._decisions.values())
            if target_manifest_hash:
                results = [d for d in results if d.target_manifest_hash == target_manifest_hash]
            if tenant_id:
                results = [d for d in results if d.tenant_id == tenant_id]
            return results

    def save_exception(self, exception: GateException) -> None:
        with self._lock:
            self._exceptions[exception.exception_id] = exception

    def get_exception(self, exception_id: str) -> GateException | None:
        with self._lock:
            return self._exceptions.get(exception_id)

    def save_schedule(self, schedule: EvalSchedule, expected_revision: int | None = None) -> None:
        with self._lock:
            existing = self._schedules.get(schedule.schedule_id)
            if expected_revision is not None and existing:
                if existing.revision != expected_revision:
                    raise EvaluationVersionConflictError(
                        f"Schedule {schedule.schedule_id} revision mismatch: expected {expected_revision}, got {existing.revision}"
                    )
            self._schedules[schedule.schedule_id] = schedule

    def get_schedule(self, schedule_id: str) -> EvalSchedule | None:
        with self._lock:
            return self._schedules.get(schedule_id)

    def list_schedules(self, tenant_id: str | None = None) -> list[EvalSchedule]:
        with self._lock:
            if tenant_id:
                return [s for s in self._schedules.values() if s.tenant_id == tenant_id]
            return list(self._schedules.values())

    def save_quality_case(self, link: QualityCaseLink) -> None:
        with self._lock:
            self._quality_cases[link.quality_case_id] = link

    def get_quality_case(self, quality_case_id: str) -> QualityCaseLink | None:
        with self._lock:
            return self._quality_cases.get(quality_case_id)

    def get_quality_case_by_execution(self, execution_id: str) -> QualityCaseLink | None:
        with self._lock:
            return next(
                (c for c in self._quality_cases.values() if c.execution_id == execution_id),
                None,
            )

    def save_active_pointer(
        self, pointer: ActiveReleasePointer, expected_etag: int | None = None
    ) -> None:
        with self._lock:
            key = (pointer.tenant_id, pointer.environment, pointer.target_type)
            existing = self._pointers.get(key)
            if expected_etag is not None and existing:
                if existing.etag != expected_etag:
                    raise EvaluationVersionConflictError(
                        f"Active pointer {key} etag mismatch: expected {expected_etag}, got {existing.etag}"
                    )
            elif expected_etag is not None and not existing and expected_etag != 0:
                raise EvaluationVersionConflictError(
                    f"Active pointer {key} does not exist for expected etag {expected_etag}"
                )
            self._pointers[key] = pointer

    def get_active_pointer(
        self, tenant_id: str, environment: str, target_type: str
    ) -> ActiveReleasePointer | None:
        with self._lock:
            return self._pointers.get((tenant_id, environment, target_type))

    def list_active_pointers(self, tenant_id: str | None = None) -> list[ActiveReleasePointer]:
        with self._lock:
            if tenant_id:
                return [p for p in self._pointers.values() if p.tenant_id == tenant_id]
            return list(self._pointers.values())

    def save_break_glass(self, bg: BreakGlassRequest) -> None:
        with self._lock:
            self._break_glasses[bg.break_glass_id] = bg

    def get_break_glass(self, break_glass_id: str) -> BreakGlassRequest | None:
        with self._lock:
            return self._break_glasses.get(break_glass_id)

    def save_activation_audit(self, audit: ActivationAuditRecord) -> None:
        with self._lock:
            self._activation_audits.append(audit)

    def list_activation_audits(self, tenant_id: str | None = None) -> list[ActivationAuditRecord]:
        with self._lock:
            if tenant_id:
                return [a for a in self._activation_audits if a.tenant_id == tenant_id]
            return list(self._activation_audits)

    def save_schedule_dispatch(self, dispatch: ScheduleDispatchResult) -> bool:
        """Atomically saves dispatch if logical_key does not exist. Returns True if created, False if duplicate."""
        with self._lock:
            if dispatch.logical_key in self._dispatches:
                return False
            self._dispatches[dispatch.logical_key] = dispatch
            return True

    def get_schedule_dispatch(self, logical_key: str) -> ScheduleDispatchResult | None:
        with self._lock:
            return self._dispatches.get(logical_key)


QualityGateRepository = InMemoryQualityGateRepository


from .file_gate_repository import FileQualityGateRepository
from .firestore_gate_repository import FirestoreQualityGateRepository

__all__ = [
    "FileQualityGateRepository",
    "FirestoreQualityGateRepository",
    "InMemoryQualityGateRepository",
    "QualityGateRepository",
    "QualityGateRepositoryProtocol",
]
