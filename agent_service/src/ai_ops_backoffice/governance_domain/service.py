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


from .flags_mixin import GovernanceFlagsMixin
from .models_mixin import GovernanceModelsMixin
from .policies_mixin import GovernancePoliciesMixin
from .prompts_mixin import GovernancePromptsMixin
from .roles_mixin import GovernanceRolesMixin
from .search_audit_mixin import GovernanceSearchAuditMixin


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

class GovernanceService(
    GovernancePromptsMixin,
    GovernanceModelsMixin,
    GovernanceFlagsMixin,
    GovernanceRolesMixin,
    GovernancePoliciesMixin,
    GovernanceSearchAuditMixin,
):
    def __init__(
        self,
        repository: GovernanceRepository,
        *,
        clock: Clock | None = None,
        eval_flow_harness: PromptFlowHarness | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or utc_now
        self._eval_flow_harness = eval_flow_harness

    def _require(self, actor: ActorContext, capability: str) -> None:
        if actor.user_id in self._repository.load().revoked_principals:
            raise GovernanceAuthorizationError("principal access has been revoked")
        if not actor.has_capability(capability):
            raise GovernanceAuthorizationError(f"missing capability {capability}")

    def _audit(
        self,
        *,
        action: str,
        actor: ActorContext,
        target_type: str,
        target_id: str,
        version_id: str | None = None,
        reason: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> GovernanceAuditEvent:
        return GovernanceAuditEvent(
            audit_id=str(uuid.uuid4()),
            action=action,
            actor_id=actor.user_id,
            actor_role=actor.role,
            target_type=target_type,  # type: ignore[arg-type]
            target_id=target_id,
            version_id=version_id,
            reason=reason,
            before=redact_secrets(before) if before else None,
            after=redact_secrets(after) if after else None,
            correlation_id=correlation_id,
            occurred_at=self._clock(),
        )

    def _seed(self, state: GovernanceState) -> GovernanceState:
        if state.prompts:
            return state
        now = self._clock()
        prompt, version = _baseline_prompt(now)
        model, model_version = _baseline_model(now)
        flags, flag_versions = _baseline_flags(now)
        masking = MaskingPolicyVersion(
            version_id=str(uuid.uuid4()),
            policy_version=MASKING_POLICY_VERSION,
            status="ACTIVE",
            rules_hash=resolve_masking_pack(MASKING_POLICY_VERSION).rules_hash,
            created_by="system-baseline",
            created_at=now,
            approved_by="system-baseline",
            activated_by="system-baseline",
            activated_at=now,
            change_reason="import code-based masking policy",
        )
        retention = RetentionPolicyVersion(
            version_id=str(uuid.uuid4()),
            policy_id="operational-events",
            status="ACTIVE",
            ttl_days=365,
            migration_plan="baseline import; no TTL change",
            created_by="system-baseline",
            created_at=now,
            approved_by="system-baseline",
            activated_by="system-baseline",
            activated_at=now,
            change_reason="import existing retention baseline",
        )
        return replace_model(
            state,
            prompts=(prompt,),
            prompt_versions=(version,),
            model_configs=(model,),
            model_versions=(model_version,),
            flags=tuple(flags),
            flag_versions=tuple(flag_versions),
            masking_policies=(masking,),
            retention_policies=(retention,),
        )

    def _mutate(self, operation: Callable[[GovernanceState], tuple[GovernanceState, dict[str, Any]]]) -> dict[str, Any]:
        def wrapped(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            seeded = self._seed(state)
            next_state, result = operation(seeded)
            return replace_model(next_state, revision=seeded.revision + 1), result

        return self._repository.mutate(wrapped)

    def _ensured(self) -> GovernanceState:
        loaded = self._repository.load()
        if loaded.prompts:
            return loaded
        self._mutate(lambda state: (state, {"seeded": True}))
        return self._repository.load()
