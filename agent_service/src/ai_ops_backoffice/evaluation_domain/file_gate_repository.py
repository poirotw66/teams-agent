"""File-backed quality gate repository with locking and atomic writes."""

from __future__ import annotations

import fcntl
import os
import sys
import uuid
from pathlib import Path
from typing import Any

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
from .gate_repository import InMemoryQualityGateRepository
from .json_record_io import iter_json_models, iter_jsonl_models


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
        self._pointers_dir = self._dir / "pointers"
        self._break_glasses_dir = self._dir / "break_glasses"
        self._dispatches_dir = self._dir / "dispatches"
        self._audits_file = self._dir / "activation_audits.jsonl"
        self._lock_file = self._dir / ".gate.lock"

        for d in (
            self._policies_dir,
            self._versions_dir,
            self._decisions_dir,
            self._exceptions_dir,
            self._schedules_dir,
            self._links_dir,
            self._pointers_dir,
            self._break_glasses_dir,
            self._dispatches_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        self._sync_from_disk()

    def _sync_from_disk(self) -> None:
        with self._lock:
            self._policies = {
                path.stem: policy
                for path, policy in iter_json_models(self._policies_dir, GatePolicy)
            }
            self._versions = {
                (version.policy_id, version.version): version
                for _, version in iter_json_models(self._versions_dir, GatePolicyVersion)
            }
            self._decisions = {
                decision.decision_id: decision
                for _, decision in iter_json_models(self._decisions_dir, GateDecision)
            }
            self._exceptions = {
                exception.exception_id: exception
                for _, exception in iter_json_models(self._exceptions_dir, GateException)
            }
            self._schedules = {
                schedule.schedule_id: schedule
                for _, schedule in iter_json_models(self._schedules_dir, EvalSchedule)
            }
            self._quality_cases = {
                link.quality_case_id: link
                for _, link in iter_json_models(self._links_dir, QualityCaseLink)
            }
            self._pointers = {
                (pointer.tenant_id, pointer.environment, pointer.target_type): pointer
                for _, pointer in iter_json_models(self._pointers_dir, ActiveReleasePointer)
            }
            self._break_glasses = {
                request.break_glass_id: request
                for _, request in iter_json_models(self._break_glasses_dir, BreakGlassRequest)
            }
            self._dispatches = {
                dispatch.logical_key: dispatch
                for _, dispatch in iter_json_models(self._dispatches_dir, ScheduleDispatchResult)
            }
            self._activation_audits = list(
                iter_jsonl_models(self._audits_file, ActivationAuditRecord)
            )

    def _write_record_atomic(self, target: Path, content: str) -> None:
        temp = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with temp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, target)
        if sys.platform != "win32":
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

    def save_policy(self, policy: GatePolicy, expected_version: int | None = None) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_policy(
                policy, expected_version=expected_version
            )
            target = self._policies_dir / f"{policy.policy_id}.json"
            self._write_record_atomic(target, policy.model_dump_json(indent=2))

        self._with_lock(_op)

    def save_version(self, version: GatePolicyVersion, expected_etag: int | None = None) -> None:
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

    def save_schedule(self, schedule: EvalSchedule, expected_revision: int | None = None) -> None:
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
        return super().list_decisions(
            target_manifest_hash=target_manifest_hash, tenant_id=tenant_id
        )

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

    def get_quality_case_by_execution(self, execution_id: str) -> QualityCaseLink | None:
        self._sync_from_disk()
        return super().get_quality_case_by_execution(execution_id)

    def save_active_pointer(
        self, pointer: ActiveReleasePointer, expected_etag: int | None = None
    ) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_active_pointer(pointer, expected_etag)
            target = (
                self._pointers_dir
                / f"{pointer.tenant_id}_{pointer.environment}_{pointer.target_type}.json"
            )
            self._write_record_atomic(target, pointer.model_dump_json(indent=2))

        self._with_lock(_op)

    def get_active_pointer(
        self, tenant_id: str, environment: str, target_type: str
    ) -> ActiveReleasePointer | None:
        self._sync_from_disk()
        return super().get_active_pointer(tenant_id, environment, target_type)

    def list_active_pointers(self, tenant_id: str | None = None) -> list[ActiveReleasePointer]:
        self._sync_from_disk()
        return super().list_active_pointers(tenant_id=tenant_id)

    def save_break_glass(self, bg: BreakGlassRequest) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_break_glass(bg)
            target = self._break_glasses_dir / f"{bg.break_glass_id}.json"
            self._write_record_atomic(target, bg.model_dump_json(indent=2))

        self._with_lock(_op)

    def get_break_glass(self, break_glass_id: str) -> BreakGlassRequest | None:
        self._sync_from_disk()
        return super().get_break_glass(break_glass_id)

    def save_activation_audit(self, audit: ActivationAuditRecord) -> None:
        def _op() -> None:
            super(FileQualityGateRepository, self).save_activation_audit(audit)
            with self._audits_file.open("a", encoding="utf-8") as f:
                f.write(audit.model_dump_json() + "\n")
                f.flush()
                os.fsync(f.fileno())

        self._with_lock(_op)

    def list_activation_audits(self, tenant_id: str | None = None) -> list[ActivationAuditRecord]:
        self._sync_from_disk()
        return super().list_activation_audits(tenant_id=tenant_id)

    def save_schedule_dispatch(self, dispatch: ScheduleDispatchResult) -> bool:
        def _op() -> bool:
            created = super(FileQualityGateRepository, self).save_schedule_dispatch(dispatch)
            if created:
                safe_key = "".join(
                    c if c.isalnum() or c in "-_" else "_" for c in dispatch.logical_key
                )
                target = self._dispatches_dir / f"{safe_key}.json"
                self._write_record_atomic(target, dispatch.model_dump_json(indent=2))
            return created

        return self._with_lock(_op)

    def get_schedule_dispatch(self, logical_key: str) -> ScheduleDispatchResult | None:
        self._sync_from_disk()
        return super().get_schedule_dispatch(logical_key)
