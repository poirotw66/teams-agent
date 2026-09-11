from __future__ import annotations

import fcntl
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Protocol

from .errors import EvaluationNotFoundError, EvaluationVersionConflictError
from .gate_models import (
    EvalSchedule,
    GateDecision,
    GateException,
    GatePolicy,
    GatePolicyVersion,
    QualityCaseLink,
)


class QualityGateRepositoryProtocol(Protocol):
    def save_policy(
        self, policy: GatePolicy, expected_version: int | None = None
    ) -> None: ...

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

    def get_quality_case_by_execution(
        self, execution_id: str
    ) -> QualityCaseLink | None: ...


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

    def save_policy(
        self, policy: GatePolicy, expected_version: int | None = None
    ) -> None:
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

    def save_version(
        self, version: GatePolicyVersion, expected_etag: int | None = None
    ) -> None:
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
                results = [
                    d for d in results if d.target_manifest_hash == target_manifest_hash
                ]
            if tenant_id:
                results = [d for d in results if d.tenant_id == tenant_id]
            return results

    def save_exception(self, exception: GateException) -> None:
        with self._lock:
            self._exceptions[exception.exception_id] = exception

    def get_exception(self, exception_id: str) -> GateException | None:
        with self._lock:
            return self._exceptions.get(exception_id)

    def save_schedule(
        self, schedule: EvalSchedule, expected_revision: int | None = None
    ) -> None:
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

    def get_quality_case_by_execution(
        self, execution_id: str
    ) -> QualityCaseLink | None:
        with self._lock:
            return next(
                (
                    c
                    for c in self._quality_cases.values()
                    if c.execution_id == execution_id
                ),
                None,
            )


QualityGateRepository = InMemoryQualityGateRepository


class FileQualityGateRepository(InMemoryQualityGateRepository):
    """Durable file-based quality gate repository with cross-process locking and atomic writes."""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self._dir = directory
        self._policies_dir = self._dir / "policies"
        self._versions_dir = self._dir / "versions"
        self._decisions_dir = self._dir / "decisions"
        self._exceptions_dir = self._dir / "exceptions"
        self._schedules_dir = self._dir / "schedules"
        self._links_dir = self._dir / "links"
        self._lock_file = self._dir / ".gate.lock"

        for d in (
            self._policies_dir,
            self._versions_dir,
            self._decisions_dir,
            self._exceptions_dir,
            self._schedules_dir,
            self._links_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        self._sync_from_disk()

    def _sync_from_disk(self) -> None:
        with self._lock:
            policies: dict[str, GatePolicy] = {}
            for p in self._policies_dir.glob("*.json"):
                try:
                    policies[p.stem] = GatePolicy.model_validate_json(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
            self._policies = policies

            versions: dict[tuple[str, int], GatePolicyVersion] = {}
            for p in self._versions_dir.glob("*.json"):
                try:
                    v = GatePolicyVersion.model_validate_json(p.read_text(encoding="utf-8"))
                    versions[(v.policy_id, v.version)] = v
                except Exception:
                    continue
            self._versions = versions

            decisions: dict[str, GateDecision] = {}
            for p in self._decisions_dir.glob("*.json"):
                try:
                    d = GateDecision.model_validate_json(p.read_text(encoding="utf-8"))
                    decisions[d.decision_id] = d
                except Exception:
                    continue
            self._decisions = decisions

            exceptions: dict[str, GateException] = {}
            for p in self._exceptions_dir.glob("*.json"):
                try:
                    e = GateException.model_validate_json(p.read_text(encoding="utf-8"))
                    exceptions[e.exception_id] = e
                except Exception:
                    continue
            self._exceptions = exceptions

            schedules: dict[str, EvalSchedule] = {}
            for p in self._schedules_dir.glob("*.json"):
                try:
                    s = EvalSchedule.model_validate_json(p.read_text(encoding="utf-8"))
                    schedules[s.schedule_id] = s
                except Exception:
                    continue
            self._schedules = schedules

            links: dict[str, QualityCaseLink] = {}
            for p in self._links_dir.glob("*.json"):
                try:
                    l = QualityCaseLink.model_validate_json(p.read_text(encoding="utf-8"))
                    links[l.quality_case_id] = l
                except Exception:
                    continue
            self._quality_cases = links

    def _write_record_atomic(self, target: Path, content: str) -> None:
        temp = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with temp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
        pfd = os.open(str(target.parent), os.O_RDONLY)
        try:
            os.fsync(pfd)
        finally:
            os.close(pfd)

    def _with_lock(self, fn: Any) -> Any:
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_file.open("a+") as lh:
            fcntl.flock(lh.fileno(), fcntl.LOCK_EX)
            try:
                self._sync_from_disk()
                return fn()
            finally:
                fcntl.flock(lh.fileno(), fcntl.LOCK_UN)

    def save_policy(
        self, policy: GatePolicy, expected_version: int | None = None
    ) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_policy(
                policy, expected_version=expected_version
            )
            target = self._policies_dir / f"{policy.policy_id}.json"
            self._write_record_atomic(target, policy.model_dump_json(indent=2))

        self._with_lock(_op)

    def save_version(
        self, version: GatePolicyVersion, expected_etag: int | None = None
    ) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_version(
                version, expected_etag=expected_etag
            )
            target = self._versions_dir / f"{version.policy_id}_{version.version}.json"
            self._write_record_atomic(target, version.model_dump_json(indent=2))

        self._with_lock(_op)

    def save_decision(self, decision: GateDecision) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_decision(decision)
            target = self._decisions_dir / f"{decision.decision_id}.json"
            self._write_record_atomic(target, decision.model_dump_json(indent=2))

        self._with_lock(_op)

    def save_exception(self, exception: GateException) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_exception(exception)
            target = self._exceptions_dir / f"{exception.exception_id}.json"
            self._write_record_atomic(target, exception.model_dump_json(indent=2))

        self._with_lock(_op)

    def save_schedule(
        self, schedule: EvalSchedule, expected_revision: int | None = None
    ) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_schedule(
                schedule, expected_revision=expected_revision
            )
            target = self._schedules_dir / f"{schedule.schedule_id}.json"
            self._write_record_atomic(target, schedule.model_dump_json(indent=2))

        self._with_lock(_op)

    def save_quality_case(self, link: QualityCaseLink) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_quality_case(link)
            target = self._links_dir / f"{link.quality_case_id}.json"
            self._write_record_atomic(target, link.model_dump_json(indent=2))

        self._with_lock(_op)

    def get_policy(self, policy_id: str) -> GatePolicy | None:
        self._sync_from_disk()
        return super().get_policy(policy_id)

    def list_policies(self, tenant_id: str | None = None) -> list[GatePolicy]:
        self._sync_from_disk()
        return super().list_policies(tenant_id=tenant_id)

    def get_version(self, policy_id: str, version: int) -> GatePolicyVersion | None:
        self._sync_from_disk()
        return super().get_version(policy_id, version)

    def list_versions(self, policy_id: str) -> list[GatePolicyVersion]:
        self._sync_from_disk()
        return super().list_versions(policy_id)

    def get_decision(self, decision_id: str) -> GateDecision | None:
        self._sync_from_disk()
        return super().get_decision(decision_id)

    def list_decisions(
        self, target_manifest_hash: str | None = None, tenant_id: str | None = None
    ) -> list[GateDecision]:
        self._sync_from_disk()
        return super().list_decisions(target_manifest_hash=target_manifest_hash, tenant_id=tenant_id)

    def get_exception(self, exception_id: str) -> GateException | None:
        self._sync_from_disk()
        return super().get_exception(exception_id)

    def get_schedule(self, schedule_id: str) -> EvalSchedule | None:
        self._sync_from_disk()
        return super().get_schedule(schedule_id)

    def list_schedules(self, tenant_id: str | None = None) -> list[EvalSchedule]:
        self._sync_from_disk()
        return super().list_schedules(tenant_id=tenant_id)

    def get_quality_case(self, quality_case_id: str) -> QualityCaseLink | None:
        self._sync_from_disk()
        return super().get_quality_case(quality_case_id)

    def get_quality_case_by_execution(
        self, execution_id: str
    ) -> QualityCaseLink | None:
        self._sync_from_disk()
        return super().get_quality_case_by_execution(execution_id)


class FirestoreQualityGateRepository:
    """Production GCP Firestore repository for Gate policies, versions, decisions, exceptions, and schedules."""

    def __init__(self, client: Any, prefix: str = "ai_ops_gate") -> None:
        self._client = client
        self._prefix = prefix

    def _col(self, suffix: str) -> Any:
        return self._client.collection(f"{self._prefix}_{suffix}")

    def save_policy(
        self, policy: GatePolicy, expected_version: int | None = None
    ) -> None:
        ref = self._col("policies").document(policy.policy_id)
        if expected_version is not None:
            doc = ref.get()
            if doc.exists and doc.to_dict().get("current_version") != expected_version:
                raise EvaluationVersionConflictError(
                    f"Policy version conflict for {policy.policy_id}"
                )
        ref.set(json.loads(policy.model_dump_json()))

    def get_policy(self, policy_id: str) -> GatePolicy | None:
        doc = self._col("policies").document(policy_id).get()
        if not doc.exists:
            return None
        return GatePolicy.model_validate(doc.to_dict())

    def list_policies(self, tenant_id: str | None = None) -> list[GatePolicy]:
        q = self._col("policies")
        if tenant_id:
            q = q.where("tenant_id", "==", tenant_id)
        return [GatePolicy.model_validate(d.to_dict()) for d in q.stream()]

    def save_version(
        self, version: GatePolicyVersion, expected_etag: int | None = None
    ) -> None:
        doc_id = f"{version.policy_id}_{version.version}"
        ref = self._col("versions").document(doc_id)
        if expected_etag is not None:
            doc = ref.get()
            if doc.exists and doc.to_dict().get("etag") != expected_etag:
                raise EvaluationVersionConflictError(
                    f"Policy version etag conflict for {doc_id}"
                )
        ref.set(json.loads(version.model_dump_json()))

    def get_version(self, policy_id: str, version: int) -> GatePolicyVersion | None:
        doc_id = f"{policy_id}_{version}"
        doc = self._col("versions").document(doc_id).get()
        if not doc.exists:
            return None
        return GatePolicyVersion.model_validate(doc.to_dict())

    def list_versions(self, policy_id: str) -> list[GatePolicyVersion]:
        q = self._col("versions").where("policy_id", "==", policy_id)
        return [GatePolicyVersion.model_validate(d.to_dict()) for d in q.stream()]

    def save_decision(self, decision: GateDecision) -> None:
        ref = self._col("decisions").document(decision.decision_id)
        ref.set(json.loads(decision.model_dump_json()))

    def get_decision(self, decision_id: str) -> GateDecision | None:
        doc = self._col("decisions").document(decision_id).get()
        if not doc.exists:
            return None
        return GateDecision.model_validate(doc.to_dict())

    def list_decisions(
        self, target_manifest_hash: str | None = None, tenant_id: str | None = None
    ) -> list[GateDecision]:
        q = self._col("decisions")
        if target_manifest_hash:
            q = q.where("target_manifest_hash", "==", target_manifest_hash)
        if tenant_id:
            q = q.where("tenant_id", "==", tenant_id)
        return [GateDecision.model_validate(d.to_dict()) for d in q.stream()]

    def save_exception(self, exception: GateException) -> None:
        ref = self._col("exceptions").document(exception.exception_id)
        ref.set(json.loads(exception.model_dump_json()))

    def get_exception(self, exception_id: str) -> GateException | None:
        doc = self._col("exceptions").document(exception_id).get()
        if not doc.exists:
            return None
        return GateException.model_validate(doc.to_dict())

    def save_schedule(
        self, schedule: EvalSchedule, expected_revision: int | None = None
    ) -> None:
        ref = self._col("schedules").document(schedule.schedule_id)
        if expected_revision is not None:
            doc = ref.get()
            if doc.exists and doc.to_dict().get("revision") != expected_revision:
                raise EvaluationVersionConflictError(
                    f"Schedule revision conflict for {schedule.schedule_id}"
                )
        ref.set(json.loads(schedule.model_dump_json()))

    def get_schedule(self, schedule_id: str) -> EvalSchedule | None:
        doc = self._col("schedules").document(schedule_id).get()
        if not doc.exists:
            return None
        return EvalSchedule.model_validate(doc.to_dict())

    def list_schedules(self, tenant_id: str | None = None) -> list[EvalSchedule]:
        q = self._col("schedules")
        if tenant_id:
            q = q.where("tenant_id", "==", tenant_id)
        return [EvalSchedule.model_validate(d.to_dict()) for d in q.stream()]

    def save_quality_case(self, link: QualityCaseLink) -> None:
        ref = self._col("links").document(link.quality_case_id)
        ref.set(json.loads(link.model_dump_json()))

    def get_quality_case(self, quality_case_id: str) -> QualityCaseLink | None:
        doc = self._col("links").document(quality_case_id).get()
        if not doc.exists:
            return None
        return QualityCaseLink.model_validate(doc.to_dict())

    def get_quality_case_by_execution(
        self, execution_id: str
    ) -> QualityCaseLink | None:
        q = self._col("links").where("execution_id", "==", execution_id).limit(1)
        docs = list(q.stream())
        if not docs:
            return None
        return QualityCaseLink.model_validate(docs[0].to_dict())
