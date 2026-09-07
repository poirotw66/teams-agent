from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime
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

class GovernanceRolesMixin:
    def request_role_change(
        self,
        *,
        target_principal: str,
        target_role: str | None,
        add_capabilities: tuple[str, ...],
        remove_capabilities: tuple[str, ...],
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["role_request"])
        added = set(add_capabilities)
        owned = set(CAPABILITIES.get(actor.role, ()))
        if target_principal in {actor.user_id, actor.role} and added - owned:
            raise GovernanceAuthorizationError("operators cannot grant themselves higher privileges")

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            change = RoleMappingChange(
                change_id=str(uuid.uuid4()),
                target_principal=target_principal,
                target_role=target_role,
                add_capabilities=add_capabilities,
                remove_capabilities=remove_capabilities,
                status="REQUESTED",
                requested_by=actor.user_id,
                requested_at=self._clock(),
                reason=reason,
            )
            audit = self._audit(
                action="ROLE_MAPPING_REQUESTED", actor=actor, target_type="ROLE_MAPPING",
                target_id=change.change_id, reason=reason, after=change.model_dump(mode="json"),
            )
            result = {"change": change.model_dump(mode="json")}
            return replace_model(
                state, role_changes=(*state.role_changes, change), audits=(*state.audits, audit)
            ), result

        return self._mutate(operation)

    def approve_role_change(self, *, change_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["role_approve"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            change = next((item for item in state.role_changes if item.change_id == change_id), None)
            if change is None:
                raise GovernanceNotFoundError(change_id)
            if change.requested_by == actor.user_id:
                raise GovernanceAuthorizationError("requester cannot approve their own role mapping")
            if change.status != "REQUESTED":
                raise GovernanceTransitionError("role mapping is not awaiting approval")
            updated = replace_model(
                change, status="APPROVED", decided_by=actor.user_id, decided_at=self._clock(), reason=reason,
            )
            granted = dict(state.granted_capabilities)
            before_caps = tuple(sorted(granted.get(change.target_principal, ())))
            current = set(before_caps)
            current.update(change.add_capabilities)
            current.difference_update(change.remove_capabilities)
            after_caps = tuple(sorted(current))
            granted[change.target_principal] = after_caps
            audit = self._audit(
                action="ROLE_MAPPING_APPROVED", actor=actor, target_type="ROLE_MAPPING",
                target_id=change_id, reason=reason,
                before={"principal": change.target_principal, "capabilities": list(before_caps), "status": "REQUESTED"},
                after={"principal": change.target_principal, "capabilities": list(after_caps), "status": "APPROVED"},
            )
            return replace_model(
                state,
                role_changes=_upsert(state.role_changes, updated, "change_id"),
                granted_capabilities=granted,
                audits=(*state.audits, audit),
            ), {"change": updated.model_dump(mode="json")}

        return self._mutate(operation)

    def revoke_principal(self, *, principal: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["role_revoke"])
        if principal == actor.user_id:
            raise GovernanceAuthorizationError("operators cannot use revoke to alter their own standing")

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            if principal in state.revoked_principals:
                return state, {"revoked": True, "principal": principal}
            audit = self._audit(
                action="PRINCIPAL_REVOKED", actor=actor, target_type="ROLE_MAPPING",
                target_id=principal, reason=reason,
                before={"principal": principal, "revoked": False},
                after={"principal": principal, "revoked": True},
            )
            return replace_model(
                state,
                revoked_principals=(*state.revoked_principals, principal),
                audits=(*state.audits, audit),
            ), {"revoked": True, "principal": principal}

        return self._mutate(operation)

    def list_role_changes(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["role"])
        return [item.model_dump(mode="json") for item in self._ensured().role_changes]
