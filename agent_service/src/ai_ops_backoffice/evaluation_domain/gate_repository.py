from __future__ import annotations

import threading

from .gate_models import (
    EvalSchedule,
    GateDecision,
    GateException,
    GatePolicy,
    GatePolicyVersion,
    QualityCaseLink,
)


class QualityGateRepository:
    """Thread-safe in-memory store for gate policies, versions, decisions, exceptions, and schedules."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._policies: dict[str, GatePolicy] = {}
        self._versions: dict[tuple[str, int], GatePolicyVersion] = {}
        self._decisions: dict[str, GateDecision] = {}
        self._exceptions: dict[str, GateException] = {}
        self._schedules: dict[str, EvalSchedule] = {}
        self._quality_cases: dict[str, QualityCaseLink] = {}

    def save_policy(self, policy: GatePolicy) -> None:
        with self._lock:
            self._policies[policy.policy_id] = policy

    def get_policy(self, policy_id: str) -> GatePolicy | None:
        with self._lock:
            return self._policies.get(policy_id)

    def list_policies(self, tenant_id: str | None = None) -> list[GatePolicy]:
        with self._lock:
            if tenant_id:
                return [p for p in self._policies.values() if p.tenant_id == tenant_id]
            return list(self._policies.values())

    def save_version(self, version: GatePolicyVersion) -> None:
        with self._lock:
            self._versions[(version.policy_id, version.version)] = version

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

    def list_decisions(self, target_manifest_hash: str | None = None) -> list[GateDecision]:
        with self._lock:
            if target_manifest_hash:
                return [d for d in self._decisions.values() if d.target_manifest_hash == target_manifest_hash]
            return list(self._decisions.values())

    def save_exception(self, exception: GateException) -> None:
        with self._lock:
            self._exceptions[exception.exception_id] = exception

    def get_exception(self, exception_id: str) -> GateException | None:
        with self._lock:
            return self._exceptions.get(exception_id)

    def save_schedule(self, schedule: EvalSchedule) -> None:
        with self._lock:
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
