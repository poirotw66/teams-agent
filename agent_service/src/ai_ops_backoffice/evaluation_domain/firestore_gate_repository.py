"""Firestore-backed quality gate repository for production persistence."""

from __future__ import annotations

import json
from typing import Any

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


class FirestoreQualityGateRepository:
    """Production GCP Firestore repository for Gate policies, versions, decisions, exceptions, and schedules."""

    def __init__(self, client: Any, prefix: str = "ai_ops_gate") -> None:
        self._client = client
        self._prefix = prefix

    def _col(self, suffix: str) -> Any:
        return self._client.collection(f"{self._prefix}_{suffix}")

    def save_policy(self, policy: GatePolicy, expected_version: int | None = None) -> None:
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

    def save_version(self, version: GatePolicyVersion, expected_etag: int | None = None) -> None:
        doc_id = f"{version.policy_id}_{version.version}"
        ref = self._col("versions").document(doc_id)
        if expected_etag is not None:
            doc = ref.get()
            if doc.exists and doc.to_dict().get("etag") != expected_etag:
                raise EvaluationVersionConflictError(f"Policy version etag conflict for {doc_id}")
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

    def save_schedule(self, schedule: EvalSchedule, expected_revision: int | None = None) -> None:
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

    def get_quality_case_by_execution(self, execution_id: str) -> QualityCaseLink | None:
        q = self._col("links").where("execution_id", "==", execution_id).limit(1)
        docs = list(q.stream())
        if not docs:
            return None
        return QualityCaseLink.model_validate(docs[0].to_dict())

    def _run_transaction(self, operation: Any) -> Any:
        if hasattr(self._client, "transaction"):
            try:
                from google.cloud.firestore_v1.transaction import transactional

                return transactional(operation)(self._client.transaction())
            except (ImportError, Exception):
                tx = self._client.transaction()
                res = operation(tx)
                if hasattr(tx, "commit"):
                    tx.commit()
                return res

        class _ImmediateTx:
            def get(self, ref: Any) -> Any:
                return ref.get()

            def set(self, ref: Any, data: Any, merge: bool = False) -> None:
                if hasattr(ref, "set"):
                    ref.set(data, merge=merge)

            def create(self, ref: Any, data: Any) -> None:
                if hasattr(ref, "create"):
                    ref.create(data)
                elif hasattr(ref, "set"):
                    ref.set(data)

        return operation(_ImmediateTx())

    @staticmethod
    def _pointer_doc_id(tenant_id: str, environment: str, target_type: str) -> str:
        return f"{tenant_id}_{environment}_{target_type}"

    def save_active_pointer(
        self, pointer: ActiveReleasePointer, expected_etag: int | None = None
    ) -> None:
        doc_id = self._pointer_doc_id(pointer.tenant_id, pointer.environment, pointer.target_type)
        ref = self._col("pointers").document(doc_id)

        def _save(transaction: Any) -> None:
            snapshot = ref.get(transaction=transaction)
            if expected_etag is not None:
                if getattr(snapshot, "exists", False):
                    current = snapshot.to_dict().get("etag")
                    if current != expected_etag:
                        raise EvaluationVersionConflictError(
                            f"Active pointer {doc_id} etag mismatch: "
                            f"expected {expected_etag}, got {current}"
                        )
                elif expected_etag != 0:
                    raise EvaluationVersionConflictError(
                        f"Active pointer {doc_id} does not exist for expected etag {expected_etag}"
                    )
            transaction.set(ref, json.loads(pointer.model_dump_json()))

        self._run_transaction(_save)

    def get_active_pointer(
        self, tenant_id: str, environment: str, target_type: str
    ) -> ActiveReleasePointer | None:
        doc_id = self._pointer_doc_id(tenant_id, environment, target_type)
        doc = self._col("pointers").document(doc_id).get()
        if not doc.exists:
            return None
        return ActiveReleasePointer.model_validate(doc.to_dict())

    def list_active_pointers(self, tenant_id: str | None = None) -> list[ActiveReleasePointer]:
        q = self._col("pointers")
        if tenant_id:
            q = q.where("tenant_id", "==", tenant_id)
        return [ActiveReleasePointer.model_validate(d.to_dict()) for d in q.stream()]

    def save_break_glass(self, bg: BreakGlassRequest) -> None:
        ref = self._col("break_glasses").document(bg.break_glass_id)
        ref.set(json.loads(bg.model_dump_json()))

    def get_break_glass(self, break_glass_id: str) -> BreakGlassRequest | None:
        doc = self._col("break_glasses").document(break_glass_id).get()
        if not doc.exists:
            return None
        return BreakGlassRequest.model_validate(doc.to_dict())

    def save_activation_audit(self, audit: ActivationAuditRecord) -> None:
        ref = self._col("activation_audits").document(audit.activation_id)
        ref.set(json.loads(audit.model_dump_json()))

    def list_activation_audits(self, tenant_id: str | None = None) -> list[ActivationAuditRecord]:
        q = self._col("activation_audits")
        if tenant_id:
            q = q.where("tenant_id", "==", tenant_id)
        return [ActivationAuditRecord.model_validate(d.to_dict()) for d in q.stream()]

    def save_schedule_dispatch(self, dispatch: ScheduleDispatchResult) -> bool:
        """Create-if-absent on logical_key. Returns True if created, False if duplicate."""
        ref = self._col("dispatches").document(dispatch.logical_key)

        def _save(transaction: Any) -> bool:
            snapshot = ref.get(transaction=transaction)
            if getattr(snapshot, "exists", False):
                return False
            data = json.loads(dispatch.model_dump_json())
            if hasattr(transaction, "create"):
                transaction.create(ref, data)
            else:
                transaction.set(ref, data)
            return True

        return bool(self._run_transaction(_save))

    def get_schedule_dispatch(self, logical_key: str) -> ScheduleDispatchResult | None:
        doc = self._col("dispatches").document(logical_key).get()
        if not doc.exists:
            return None
        return ScheduleDispatchResult.model_validate(doc.to_dict())
