"""Model config lookup, validation, and approve/activate transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from operations_core.access import ActorContext

from .constants import FALLBACK_TRIGGERS, is_allowlisted_model, normalize_allowlisted_model_id
from .errors import (
    GovernanceAuthorizationError,
    GovernanceNotFoundError,
    GovernanceTransitionError,
    GovernanceValidationError,
)
from .governance_state_ops import _upsert
from .models import (
    GovernanceAuditEvent,
    GovernanceState,
    ModelConfigRecord,
    ModelConfigVersion,
    replace_model,
    utc_now,
)
from .prompt_lifecycle_ops import _eval_for


def _find_model(state: GovernanceState, config_id: str) -> ModelConfigRecord:
    config = next((item for item in state.model_configs if item.config_id == config_id), None)
    if config is None:
        raise GovernanceNotFoundError(config_id)
    return config


def _find_model_version(state: GovernanceState, version_id: str) -> ModelConfigVersion:
    version = next((item for item in state.model_versions if item.version_id == version_id), None)
    if version is None:
        raise GovernanceNotFoundError(version_id)
    return version


def _validate_model(
    provider: str, model_id: str, fallback_model_id: str | None, fallback_on: tuple[str, ...]
) -> None:
    if not is_allowlisted_model(model_id, provider=provider):
        raise GovernanceValidationError("model is not on the provider allowlist")
    if fallback_model_id and (
        not is_allowlisted_model(fallback_model_id, provider=provider)
        or normalize_allowlisted_model_id(fallback_model_id)
        == normalize_allowlisted_model_id(model_id)
    ):
        raise GovernanceValidationError("fallback model must be a different allowlisted model")
    if set(fallback_on) - FALLBACK_TRIGGERS:
        raise GovernanceValidationError("fallback trigger is not permitted")


def _public_model(version: ModelConfigVersion) -> dict[str, Any]:
    payload = version.model_dump(mode="json")
    payload.pop("secret_value", None)
    return payload


def _approve_model(
    state: GovernanceState,
    config_id: str,
    version_id: str,
    reason: str,
    actor: ActorContext,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    version = _find_model_version(state, version_id)
    if version.config_id != config_id:
        raise GovernanceNotFoundError(version_id)
    if version.status != "EVALUATED":
        raise GovernanceTransitionError("model approval requires eval")
    if version.created_by == actor.user_id:
        raise GovernanceAuthorizationError("submitter cannot approve their own model candidate")
    run = _eval_for(state, version.eval_run_id)
    if run is None or not run.critical_passed:
        raise GovernanceTransitionError("critical model safety tests must pass before approval")
    updated = replace_model(
        version,
        status="APPROVED",
        approved_by=actor.user_id,
        approved_at=utc_now(),
        change_reason=reason,
    )
    audit = replace_model(
        audit,
        before={"status": version.status},
        after={"status": "APPROVED", "approvedBy": actor.user_id},
    )
    return replace_model(
        state,
        model_versions=_upsert(state.model_versions, updated, "version_id"),
        audits=(*state.audits, audit),
    ), {"version": _public_model(updated)}


def _activate_model(
    state: GovernanceState,
    config_id: str,
    version_id: str,
    reason: str,
    actor: ActorContext,
    now: datetime,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    config = _find_model(state, config_id)
    version = _find_model_version(state, version_id)
    if version.status != "APPROVED":
        raise GovernanceTransitionError("model activation requires approval")
    current = (
        _find_model_version(state, config.active_version_id or "")
        if config.active_version_id
        else None
    )
    retired = replace_model(current, status="RETIRED") if current else None
    updated = replace_model(
        version,
        status="ACTIVE",
        activated_by=actor.user_id,
        activated_at=now,
        change_reason=reason,
    )
    next_config = replace_model(
        config,
        active_version_id=version_id,
        previous_healthy_version_id=current.version_id if current else version_id,
        etag=config.etag + 1,
    )
    audit = replace_model(
        audit,
        before={
            "activeVersionId": current.version_id if current else None,
            "status": current.status if current else None,
        },
        after={"activeVersionId": version_id, "status": "ACTIVE", "activatedBy": actor.user_id},
    )
    versions = state.model_versions
    if retired is not None:
        versions = _upsert(versions, retired, "version_id")
    return replace_model(
        state,
        model_configs=_upsert(state.model_configs, next_config, "config_id"),
        model_versions=_upsert(versions, updated, "version_id"),
        audits=(*state.audits, audit),
    ), {"config": next_config.model_dump(mode="json"), "version": _public_model(updated)}
