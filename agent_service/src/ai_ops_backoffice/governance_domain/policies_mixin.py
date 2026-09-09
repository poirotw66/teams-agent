from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from agent_service.extractor import SYSTEM_PROMPT
from agent_service.operations.access import CAPABILITIES, ActorContext
from agent_service.operations.masking import MASKING_POLICY_VERSION, redact_secrets
from agent_service.operations.masking_rules import resolve_masking_pack

from .constants import (
    FALLBACK_TRIGGERS,
    FLAG_CATALOG,
    ISSUE_EXTRACTOR_PROMPT_ID,
    MAX_PROMPT_LENGTH,
    PROVIDER_MODELS,
    READ,
    WRITE,
)
from .errors import (
    GovernanceAuthorizationError,
    GovernanceConflictError,
    GovernanceNotFoundError,
    GovernanceTransitionError,
    GovernanceValidationError,
)
from .eval_flow import PromptFlowHarness
from .eval_runner import evaluate_model, evaluate_prompt_async
from .helpers import (
    content_hash,
    fingerprint,
    public_prompt,
    reject_secrets_and_injection,
    replay,
    require_secret_ref,
    short_version,
    sticky_bucket,
    with_idempotency,
)
from .models import (
    EvalRun,
    FlagRecord,
    FlagVersion,
    GovernanceAuditEvent,
    GovernanceState,
    MaskingPolicyVersion,
    ModelConfigRecord,
    ModelConfigVersion,
    PromptRecord,
    PromptVersion,
    RetentionPolicyVersion,
    RoleMappingChange,
    replace_model,
    utc_now,
)
from .repository import GovernanceRepository

Clock = Callable[[], datetime]




from .service_helpers import (
    _allowed,
    _upsert,
    _find_prompt,
    _find_prompt_version,
    _active_prompt,
    _find_model,
    _find_model_version,
    _baseline_prompt,
    _baseline_model,
    _baseline_flags,
    _verified_examples,
    _candidate_template,
    _eval_for,
    _approve_prompt,
    _activate_prompt,
    _validate_model,
    _public_model,
    _approve_model,
    _activate_model,
    _approve_flag,
    _activate_flag,
)

class GovernancePoliciesMixin:
    def peek_runtime_retention(self, policy_id: str = "operational-events") -> dict[str, Any] | None:
        """Read-only ACTIVE retention TTL for ops runtime."""
        state = self._repository.load()
        active = next(
            (
                item
                for item in state.retention_policies
                if item.policy_id == policy_id and item.status == "ACTIVE"
            ),
            None,
        )
        if active is None:
            return None
        return {
            "policyId": active.policy_id,
            "versionId": active.version_id,
            "ttlDays": active.ttl_days,
            "status": active.status,
        }

    def peek_runtime_masking(self) -> dict[str, Any] | None:
        """Read-only ACTIVE masking policy version for ops runtime."""
        state = self._repository.load()
        active = next(
            (item for item in state.masking_policies if item.status == "ACTIVE"),
            None,
        )
        if active is None:
            return None
        return {
            "versionId": active.version_id,
            "policyVersion": active.policy_version,
            "rulesHash": active.rules_hash,
            "status": active.status,
        }

    def list_retention_policies(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["retention"])
        return [item.model_dump(mode="json") for item in self._ensured().retention_policies]

    def list_masking_policies(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["retention"])
        return [item.model_dump(mode="json") for item in self._ensured().masking_policies]

    def create_masking_candidate(
        self,
        *,
        policy_version: str,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])
        reject_secrets_and_injection(policy_version, label="masking policy version")
        if not policy_version.strip():
            raise GovernanceValidationError("masking policy version is required")
        try:
            pack = resolve_masking_pack(policy_version.strip())
        except KeyError as exc:
            raise GovernanceValidationError(str(exc)) from exc

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = MaskingPolicyVersion(
                version_id=str(uuid.uuid4()),
                policy_version=pack.policy_version,
                status="CANDIDATE",
                rules_hash=pack.rules_hash,
                created_by=actor.user_id,
                created_at=self._clock(),
                change_reason=reason,
            )
            audit = self._audit(
                action="MASKING_CANDIDATE_CREATED",
                actor=actor,
                target_type="MASKING",
                target_id=version.policy_version,
                version_id=version.version_id,
                reason=reason,
                after={
                    **version.model_dump(mode="json"),
                    "rules": {
                        "maskEmail": pack.mask_email,
                        "maskPhone": pack.mask_phone,
                        "maskEmployeeId": pack.mask_employee_id,
                        "maskNationalId": pack.mask_national_id,
                        "maskCredentials": pack.mask_credentials,
                    },
                },
            )
            return replace_model(
                state,
                masking_policies=(*state.masking_policies, version),
                audits=(*state.audits, audit),
            ), {"policy": version.model_dump(mode="json")}

        return self._mutate(operation)

    def approve_masking(self, *, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = next(
                (item for item in state.masking_policies if item.version_id == version_id),
                None,
            )
            if version is None:
                raise GovernanceNotFoundError(version_id)
            if version.created_by == actor.user_id:
                raise GovernanceAuthorizationError(
                    "requester cannot approve their own masking policy"
                )
            if version.status != "CANDIDATE":
                raise GovernanceTransitionError("masking policy is not awaiting approval")
            updated = replace_model(
                version,
                status="APPROVED",
                approved_by=actor.user_id,
                change_reason=reason,
            )
            audit = self._audit(
                action="MASKING_APPROVED",
                actor=actor,
                target_type="MASKING",
                target_id=version.policy_version,
                version_id=version_id,
                reason=reason,
                before={"status": version.status},
                after={"status": "APPROVED", "approvedBy": actor.user_id},
            )
            return replace_model(
                state,
                masking_policies=_upsert(state.masking_policies, updated, "version_id"),
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._mutate(operation)

    def activate_masking(self, *, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = next(
                (item for item in state.masking_policies if item.version_id == version_id),
                None,
            )
            if version is None:
                raise GovernanceNotFoundError(version_id)
            if version.status != "APPROVED":
                raise GovernanceTransitionError("activation requires an approved masking policy")
            retired = [
                replace_model(item, status="RETIRED")
                if item.status == "ACTIVE" and item.version_id != version_id
                else item
                for item in state.masking_policies
            ]
            updated = replace_model(
                version,
                status="ACTIVE",
                activated_by=actor.user_id,
                activated_at=self._clock(),
                change_reason=reason,
            )
            audit = self._audit(
                action="MASKING_ACTIVATED",
                actor=actor,
                target_type="MASKING",
                target_id=version.policy_version,
                version_id=version_id,
                reason=reason,
                before={"status": version.status},
                after={"status": "ACTIVE", "activatedBy": actor.user_id},
            )
            return replace_model(
                state,
                masking_policies=_upsert(tuple(retired), updated, "version_id"),
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._mutate(operation)

    def create_retention_candidate(
        self,
        *,
        policy_id: str,
        ttl_days: int,
        migration_plan: str,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])
        if not migration_plan.strip():
            raise GovernanceValidationError("TTL changes require a migration plan")
        reject_secrets_and_injection(migration_plan, label="migration plan")

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = RetentionPolicyVersion(
                version_id=str(uuid.uuid4()),
                policy_id=policy_id,
                status="CANDIDATE",
                ttl_days=ttl_days,
                migration_plan=migration_plan,
                created_by=actor.user_id,
                created_at=self._clock(),
                change_reason=reason,
            )
            audit = self._audit(
                action="RETENTION_CANDIDATE_CREATED", actor=actor, target_type="RETENTION",
                target_id=policy_id, version_id=version.version_id, reason=reason,
                after=version.model_dump(mode="json"),
            )
            return replace_model(
                state,
                retention_policies=(*state.retention_policies, version),
                audits=(*state.audits, audit),
            ), {"policy": version.model_dump(mode="json")}

        return self._mutate(operation)

    def approve_retention(self, *, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = next((item for item in state.retention_policies if item.version_id == version_id), None)
            if version is None:
                raise GovernanceNotFoundError(version_id)
            if version.created_by == actor.user_id:
                raise GovernanceAuthorizationError("requester cannot approve their own retention policy")
            updated = replace_model(
                version, status="APPROVED", approved_by=actor.user_id, change_reason=reason,
            )
            audit = self._audit(
                action="RETENTION_APPROVED", actor=actor, target_type="RETENTION",
                target_id=version.policy_id, version_id=version_id, reason=reason,
                before={"status": version.status},
                after={"status": "APPROVED", "approvedBy": actor.user_id},
            )
            return replace_model(
                state,
                retention_policies=_upsert(state.retention_policies, updated, "version_id"),
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._mutate(operation)

    def activate_retention(self, *, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = next((item for item in state.retention_policies if item.version_id == version_id), None)
            if version is None:
                raise GovernanceNotFoundError(version_id)
            if version.status != "APPROVED":
                raise GovernanceTransitionError("activation requires an approved retention policy")
            prev_active = next((item for item in state.retention_policies if item.policy_id == version.policy_id and item.status == "ACTIVE"), None)
            retired = [
                replace_model(item, status="RETIRED")
                if item.policy_id == version.policy_id and item.status == "ACTIVE"
                else item
                for item in state.retention_policies
            ]
            updated = replace_model(
                version, status="ACTIVE", activated_by=actor.user_id, activated_at=self._clock(),
                change_reason=reason,
            )
            audit = self._audit(
                action="RETENTION_ACTIVATED", actor=actor, target_type="RETENTION",
                target_id=version.policy_id, version_id=version_id, reason=reason,
                before={"status": version.status, "ttl_days": prev_active.ttl_days if prev_active else None},
                after={"status": "ACTIVE", "ttl_days": updated.ttl_days, "activatedBy": actor.user_id},
            )
            return replace_model(
                state,
                retention_policies=_upsert(tuple(retired), updated, "version_id"),
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._mutate(operation)

    def purge_expired(
        self,
        *,
        actor: ActorContext | None = None,
        retention_days: int = 365,
        audit_retention_days: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Purge expired non-core versions and audits with permanent retention exception for active/approved versions.

        Audit records use ``audit_retention_days`` when provided (typically longer than
        operational TTL). Active/approved versions are retained permanently.
        """
        if actor is not None:
            self._require(actor, WRITE["retention_write"])

        target_now = now or self._clock()
        cutoff = target_now - timedelta(days=retention_days)
        effective_audit_days = (
            retention_days if audit_retention_days is None else max(1, int(audit_retention_days))
        )
        audit_cutoff = target_now - timedelta(days=effective_audit_days)

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            active_prompt_ids = {p.active_version_id for p in state.prompts if p.active_version_id}
            active_flag_ids = {f.active_version_id for f in state.flags if f.active_version_id}
            active_model_ids = {m.active_version_id for m in state.model_configs if m.active_version_id}
            healthy_model_ids = {
                m.previous_healthy_version_id for m in state.model_configs if m.previous_healthy_version_id
            }
            protected_model_ids = active_model_ids | healthy_model_ids

            new_flag_versions = tuple(
                v
                for v in state.flag_versions
                if v.version_id in active_flag_ids
                or v.status in ("ACTIVE", "APPROVED")
                or v.created_at >= cutoff
            )
            pruned_flags = len(state.flag_versions) - len(new_flag_versions)

            new_prompt_versions = tuple(
                v
                for v in state.prompt_versions
                if v.version_id in active_prompt_ids
                or v.status in ("ACTIVE", "APPROVED")
                or v.created_at >= cutoff
            )
            pruned_prompts = len(state.prompt_versions) - len(new_prompt_versions)

            new_model_versions = tuple(
                v
                for v in state.model_versions
                if v.version_id in protected_model_ids
                or v.status in ("ACTIVE", "APPROVED")
                or v.created_at >= cutoff
            )
            pruned_models = len(state.model_versions) - len(new_model_versions)

            new_audits = tuple(a for a in state.audits if a.occurred_at >= audit_cutoff)
            pruned_audits = len(state.audits) - len(new_audits)

            new_idempotency = tuple(i for i in state.idempotency if i.created_at >= cutoff)
            pruned_idempotency = len(state.idempotency) - len(new_idempotency)

            total_removed = (
                pruned_flags + pruned_prompts + pruned_models + pruned_audits + pruned_idempotency
            )

            audit_events = list(new_audits)
            if actor is not None and total_removed > 0:
                audit_record = self._audit(
                    action="GOVERNANCE_RETENTION_PURGE",
                    actor=actor,
                    target_type="RETENTION",
                    target_id="GOVERNANCE_RETENTION",
                    after={
                        "prunedFlags": pruned_flags,
                        "prunedPrompts": pruned_prompts,
                        "prunedModels": pruned_models,
                        "prunedAudits": pruned_audits,
                        "prunedIdempotency": pruned_idempotency,
                        "totalRemoved": total_removed,
                        "retentionDays": retention_days,
                        "auditRetentionDays": effective_audit_days,
                    },
                )
                audit_events.append(audit_record)

            new_state = replace_model(
                state,
                flag_versions=new_flag_versions,
                prompt_versions=new_prompt_versions,
                model_versions=new_model_versions,
                audits=tuple(audit_events),
                idempotency=new_idempotency,
            )

            result = {
                "flagVersions": pruned_flags,
                "promptVersions": pruned_prompts,
                "modelVersions": pruned_models,
                "audits": pruned_audits,
                "idempotency": pruned_idempotency,
                "totalRemoved": total_removed,
                "retentionDays": retention_days,
                "auditRetentionDays": effective_audit_days,
                "retentionPolicy": (
                    "Core active and approved versions retained permanently for rollback capability; "
                    f"expired candidate and retired versions older than {retention_days} days purged; "
                    f"audits retained for {effective_audit_days} days."
                ),
            }
            return new_state, result

        return self._mutate(operation)
