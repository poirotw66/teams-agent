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

class GovernanceFlagsMixin:
    def peek_runtime_flag(
        self, flag_id: str, *, environment: str = "lab"
    ) -> dict[str, Any] | None:
        """Read-only effective flag value with expiry-safe defaults."""
        from .constants import FLAG_CATALOG

        catalog = FLAG_CATALOG.get(flag_id)
        if catalog is None:
            return None
        state = self._repository.load()
        flag = next((item for item in state.flags if item.flag_id == flag_id), None)
        if flag is None:
            return {
                "flagId": flag_id,
                "value": str(catalog["default"]),
                "source": "catalog_default",
                "safetyLocked": bool(catalog["safety_locked"]),
            }
        value = flag.default_value
        source = "flag_default"
        if flag.active_version_id:
            version = next(
                (item for item in state.flag_versions if item.version_id == flag.active_version_id),
                None,
            )
            if version is not None and version.status == "ACTIVE":
                expired = version.expires_at is not None and version.expires_at <= self._clock()
                if version.environment == environment and not expired:
                    value = version.value
                    source = "active_version"
                elif expired:
                    value = flag.default_value
                    source = "expired_default"
        if flag.safety_locked and value.lower() in {"false", "disabled"}:
            value = str(catalog["default"])
            source = "safety_locked_default"
        return {
            "flagId": flag_id,
            "value": value,
            "source": source,
            "safetyLocked": flag.safety_locked,
        }

    def create_flag_candidate(
        self,
        *,
        flag_id: str,
        value: str,
        environment: str,
        expires_at: datetime | None,
        reason: str,
        actor: ActorContext,
        percent: int | None = None,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["flag_write"])
        spec = FLAG_CATALOG.get(flag_id)
        if spec is None:
            raise GovernanceValidationError(f"unknown feature flag {flag_id}")
        if spec["safety_locked"] and value.lower() in {"false", "disabled"}:
            raise GovernanceValidationError("safety-critical flags cannot be disabled from the general UI")
        if environment == "prod" and expires_at is None:
            raise GovernanceValidationError("production flags require an expiry")

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            flag = next((item for item in state.flags if item.flag_id == flag_id), None)
            if flag is None:
                raise GovernanceNotFoundError(flag_id)
            now = self._clock()
            version = FlagVersion(
                version_id=str(uuid.uuid4()),
                flag_id=flag_id,
                status="CANDIDATE",
                value=value,
                environment=environment,
                percent=percent,
                effective_at=now,
                expires_at=expires_at,
                created_by=actor.user_id,
                created_at=now,
                change_reason=reason,
            )
            next_flag = replace_model(flag, etag=flag.etag + 1)
            audit = self._audit(
                action="FLAG_CANDIDATE_CREATED", actor=actor, target_type="FLAG",
                target_id=flag_id, version_id=version.version_id, reason=reason,
                after=version.model_dump(mode="json"),
            )
            result = {"flag": next_flag.model_dump(mode="json"), "version": version.model_dump(mode="json")}
            return replace_model(
                state,
                flags=_upsert(state.flags, next_flag, "flag_id"),
                flag_versions=(*state.flag_versions, version),
                audits=(*state.audits, audit),
            ), result

        return self._mutate(operation)

    def approve_flag(self, *, flag_id: str, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["flag_approve"])
        return self._mutate(lambda state: _approve_flag(state, flag_id, version_id, reason, actor, self._audit(
            action="FLAG_APPROVED", actor=actor, target_type="FLAG",
            target_id=flag_id, version_id=version_id, reason=reason,
        )))

    def activate_flag(self, *, flag_id: str, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["flag_activate"])
        return self._mutate(lambda state: _activate_flag(
            state, flag_id, version_id, reason, actor, self._clock(),
            self._audit(
                action="FLAG_ACTIVATED", actor=actor, target_type="FLAG",
                target_id=flag_id, version_id=version_id, reason=reason,
            ),
        ))

    def effective_flag(self, flag_id: str, *, actor: ActorContext, environment: str = "lab") -> dict[str, Any]:
        self._require(actor, READ["flag"])
        state = self._ensured()
        flag = next((item for item in state.flags if item.flag_id == flag_id), None)
        if flag is None:
            raise GovernanceNotFoundError(flag_id)
        value = flag.default_value
        version = None
        if flag.active_version_id:
            version = next(item for item in state.flag_versions if item.version_id == flag.active_version_id)
            expired = version.expires_at is not None and version.expires_at <= self._clock()
            if version.status == "ACTIVE" and version.environment == environment and not expired:
                value = version.value
            elif expired:
                value = flag.default_value
        return {
            "flagId": flag_id,
            "value": value,
            "defaultValue": flag.default_value,
            "safetyLocked": flag.safety_locked,
            "version": version.model_dump(mode="json") if version else None,
        }

    def list_flags(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["flag"])
        state = self._ensured()
        return [
            {
                "flag": item.model_dump(mode="json"),
                "effective": self.effective_flag(item.flag_id, actor=actor)["value"],
                "versions": [
                    v.model_dump(mode="json")
                    for v in state.flag_versions
                    if v.flag_id == item.flag_id
                ],
            }
            for item in state.flags
        ]
