"""Prompt canary lifecycle operations for governance."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from operations_core.access import ActorContext

from .errors import GovernanceTransitionError, GovernanceValidationError
from .helpers import public_prompt
from .models import GovernanceAuditEvent, GovernanceState, replace_model
from .service_helpers import (
    _active_prompt,
    _find_prompt,
    _find_prompt_version,
    _upsert,
)

AuditFactory = Callable[..., GovernanceAuditEvent]


def start_canary_operation(
    state: GovernanceState,
    *,
    prompt_id: str,
    version_id: str,
    percent: int,
    environment: str,
    reason: str,
    actor: ActorContext,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    prompt = _find_prompt(state, prompt_id)
    version = _find_prompt_version(state, version_id)
    if version.status != "APPROVED":
        raise GovernanceTransitionError("canary requires an approved version")
    updated = replace_model(
        version,
        status="CANARY",
        canary_percent=percent,
        canary_environment=environment,
        canary_stopped=False,
        change_reason=reason,
    )
    next_prompt = replace_model(
        prompt,
        canary_version_id=version_id,
        etag=prompt.etag + 1,
    )
    audit = replace_model(
        audit,
        before={"status": version.status, "canaryVersionId": prompt.canary_version_id},
        after={
            "status": "CANARY",
            "percent": percent,
            "environment": environment,
            "canaryVersionId": version_id,
        },
    )
    result = {
        "prompt": next_prompt.model_dump(mode="json"),
        "version": public_prompt(updated, include_content=False),
    }
    return replace_model(
        state,
        prompts=_upsert(state.prompts, next_prompt, "prompt_id"),
        prompt_versions=_upsert(state.prompt_versions, updated, "version_id"),
        audits=(*state.audits, audit),
    ), result


def validate_canary_percent(percent: int) -> None:
    if percent < 1 or percent > 99:
        raise GovernanceValidationError("production canary must be a percentage between 1 and 99")


def _rollback_active_on_canary_stop(
    state: GovernanceState,
    *,
    prompt: Any,
    versions: tuple[Any, ...],
    audits: list[GovernanceAuditEvent],
    reason: str,
    actor: ActorContext,
    now: datetime,
    make_audit: AuditFactory,
) -> tuple[GovernanceState, dict[str, Any]]:
    current = _active_prompt(state, prompt.prompt_id)
    previous = _find_prompt_version(state, prompt.previous_healthy_version_id)
    failed = replace_model(current, status="RETIRED", change_reason=reason)
    restored = replace_model(
        previous,
        status="ACTIVE",
        activated_by=actor.user_id,
        activated_at=now,
        rollback_of_version_id=current.version_id,
        change_reason=reason,
    )
    next_prompt = replace_model(
        prompt,
        active_version_id=previous.version_id,
        canary_version_id=None,
        previous_healthy_version_id=previous.version_id,
        etag=prompt.etag + 1,
    )
    audits.append(
        make_audit(
            action="PROMPT_CANARY_AUTO_ROLLBACK",
            actor=actor,
            target_type="PROMPT",
            target_id=prompt.prompt_id,
            version_id=previous.version_id,
            reason=reason,
            before={"activeVersionId": current.version_id},
            after={"activeVersionId": previous.version_id},
        )
    )
    result = {
        "prompt": next_prompt.model_dump(mode="json"),
        "version": public_prompt(restored, include_content=False),
        "action": "ROLLBACK",
    }
    return replace_model(
        state,
        prompts=_upsert(state.prompts, next_prompt, "prompt_id"),
        prompt_versions=_upsert(_upsert(versions, failed, "version_id"), restored, "version_id"),
        audits=(*state.audits, *audits),
    ), result


def stop_canary_operation(
    state: GovernanceState,
    *,
    prompt_id: str,
    reason: str,
    actor: ActorContext,
    rollback: bool,
    now: datetime,
    make_audit: AuditFactory,
) -> tuple[GovernanceState, dict[str, Any]]:
    prompt = _find_prompt(state, prompt_id)
    if not prompt.canary_version_id:
        raise GovernanceTransitionError("no active canary to stop")
    canary = _find_prompt_version(state, prompt.canary_version_id)
    # Return to APPROVED so the same version can be canaried again after a
    # non-rollback stop (safety or threshold). Keep canary_stopped for audit.
    stopped = replace_model(
        canary,
        status="APPROVED",
        canary_stopped=True,
        change_reason=reason,
    )
    versions = _upsert(state.prompt_versions, stopped, "version_id")
    audits = [
        make_audit(
            action="PROMPT_CANARY_STOPPED",
            actor=actor,
            target_type="PROMPT",
            target_id=prompt_id,
            version_id=canary.version_id,
            reason=reason,
            before={"status": canary.status, "canaryPercent": canary.canary_percent},
            after={"status": stopped.status, "canaryStopped": True},
        )
    ]
    if rollback and prompt.previous_healthy_version_id:
        return _rollback_active_on_canary_stop(
            state,
            prompt=prompt,
            versions=versions,
            audits=audits,
            reason=reason,
            actor=actor,
            now=now,
            make_audit=make_audit,
        )
    next_prompt = replace_model(prompt, canary_version_id=None, etag=prompt.etag + 1)
    result = {
        "prompt": next_prompt.model_dump(mode="json"),
        "version": public_prompt(stopped, include_content=False),
        "action": "STOP",
    }
    return replace_model(
        state,
        prompts=_upsert(state.prompts, next_prompt, "prompt_id"),
        prompt_versions=versions,
        audits=(*state.audits, *audits),
    ), result


def evaluate_canary_thresholds(
    *,
    prompt_id: str,
    error_rate: float,
    negative_feedback_rate: float,
    handoff_rate: float,
    safety_alerts: int,
    sample_size: int,
) -> dict[str, Any]:
    """Classify canary metrics as CONTINUE or STOP with a stable reason string."""
    # Critical safety always wins — never wait for sample size.
    if safety_alerts > 0:
        return {"decision": "STOP", "reason": "critical safety alert"}
    if sample_size < 10:
        return {
            "decision": "CONTINUE",
            "action": "CONTINUE",
            "reason": "insufficient sample size",
            "promptId": prompt_id,
        }
    if error_rate >= 0.15 or negative_feedback_rate >= 0.25 or handoff_rate >= 0.4:
        return {"decision": "STOP", "reason": "quality or availability regression"}
    return {
        "decision": "CONTINUE",
        "action": "CONTINUE",
        "reason": "within thresholds",
        "promptId": prompt_id,
    }
