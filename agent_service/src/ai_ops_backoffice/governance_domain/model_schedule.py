"""Schedule embedding and file-search model changes without flipping the active pointer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_service.operations.access import ActorContext

from .errors import GovernanceConflictError, GovernanceTransitionError
from .model_catalog import component_effect
from .models import GovernanceAuditEvent, GovernanceState, replace_model
from .service_helpers import _find_model, _find_model_version, _public_model, _upsert

_SCHEDULE_ALLOWED = frozenset({"APPROVED", "RETIRED", "ACTIVE"})


def _require_scheduled_effect(config_id: str) -> str:
    effect = component_effect(config_id)
    if effect == "next_request":
        raise GovernanceTransitionError(
            "this component activates on the next request and cannot be scheduled"
        )
    return "reindex" if effect == "reindex" else "service_refresh"


def schedule_model_version(
    state: GovernanceState,
    *,
    config_id: str,
    version_id: str,
    reason: str,
    actor: ActorContext,
    now: datetime,
    audit: GovernanceAuditEvent,
    allow_retired: bool = False,
) -> tuple[GovernanceState, dict[str, Any]]:
    kind = _require_scheduled_effect(config_id)
    config = _find_model(state, config_id)
    if config.schedule_status in {"queued", "running"}:
        raise GovernanceConflictError("a model schedule is already in progress")
    version = _find_model_version(state, version_id)
    if version.config_id != config_id:
        raise GovernanceTransitionError("version does not belong to this model config")
    allowed = _SCHEDULE_ALLOWED if allow_retired else frozenset({"APPROVED"})
    if version.status not in allowed:
        raise GovernanceTransitionError("model schedule requires an approved version")
    if version.version_id == config.active_version_id and version.status == "ACTIVE":
        raise GovernanceTransitionError("version is already the effective model")
    next_config = replace_model(
        config,
        scheduled_version_id=version_id,
        schedule_kind=kind,
        schedule_status="queued",
        etag=config.etag + 1,
    )
    audit = replace_model(
        audit,
        before={
            "activeVersionId": config.active_version_id,
            "scheduleStatus": config.schedule_status,
        },
        after={
            "activeVersionId": config.active_version_id,
            "scheduledVersionId": version_id,
            "scheduleKind": kind,
            "scheduleStatus": "queued",
            "scheduledBy": actor.user_id,
            "scheduledAt": now.isoformat(),
        },
        reason=reason,
    )
    return replace_model(
        state,
        model_configs=_upsert(state.model_configs, next_config, "config_id"),
        audits=(*state.audits, audit),
    ), {
        "config": next_config.model_dump(mode="json"),
        "version": _public_model(version),
        "scheduled": True,
    }


def mark_model_schedule_running(
    state: GovernanceState,
    *,
    config_id: str,
    version_id: str,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    config = _find_model(state, config_id)
    if config.scheduled_version_id != version_id or config.schedule_status != "queued":
        raise GovernanceConflictError("model schedule is not queued for this version")
    next_config = replace_model(config, schedule_status="running", etag=config.etag + 1)
    audit = replace_model(
        audit,
        before={"scheduleStatus": "queued"},
        after={"scheduleStatus": "running", "scheduledVersionId": version_id},
    )
    return replace_model(
        state,
        model_configs=_upsert(state.model_configs, next_config, "config_id"),
        audits=(*state.audits, audit),
    ), {"config": next_config.model_dump(mode="json")}


def complete_model_schedule(
    state: GovernanceState,
    *,
    config_id: str,
    version_id: str,
    actor: ActorContext,
    now: datetime,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    config = _find_model(state, config_id)
    if config.scheduled_version_id != version_id or config.schedule_status not in {
        "queued",
        "running",
    }:
        raise GovernanceConflictError("model schedule is not waiting to be applied")
    version = _find_model_version(state, version_id)
    current = (
        _find_model_version(state, config.active_version_id)
        if config.active_version_id and config.active_version_id != version_id
        else None
    )
    retired = (
        replace_model(current, status="RETIRED") if current and current.status == "ACTIVE" else None
    )
    updated = replace_model(
        version,
        status="ACTIVE",
        activated_by=actor.user_id,
        activated_at=now,
        change_reason=audit.reason,
    )
    previous_healthy = current.version_id if current else config.previous_healthy_version_id
    next_config = replace_model(
        config,
        active_version_id=version_id,
        previous_healthy_version_id=previous_healthy or version_id,
        schedule_status="applied",
        etag=config.etag + 1,
    )
    audit = replace_model(
        audit,
        before={
            "activeVersionId": config.active_version_id,
            "scheduleStatus": config.schedule_status,
        },
        after={
            "activeVersionId": version_id,
            "scheduleStatus": "applied",
            "activatedBy": actor.user_id,
        },
    )
    versions = state.model_versions
    if retired is not None:
        versions = _upsert(versions, retired, "version_id")
    versions = _upsert(versions, updated, "version_id")
    return replace_model(
        state,
        model_configs=_upsert(state.model_configs, next_config, "config_id"),
        model_versions=versions,
        audits=(*state.audits, audit),
    ), {"config": next_config.model_dump(mode="json"), "version": _public_model(updated)}


def fail_model_schedule(
    state: GovernanceState,
    *,
    config_id: str,
    version_id: str,
    reason: str,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    config = _find_model(state, config_id)
    if config.scheduled_version_id != version_id or config.schedule_status not in {
        "queued",
        "running",
    }:
        raise GovernanceConflictError("model schedule is not in progress")
    version = _find_model_version(state, version_id)
    next_config = replace_model(config, schedule_status="failed", etag=config.etag + 1)
    audit = replace_model(
        audit,
        before={
            "activeVersionId": config.active_version_id,
            "scheduleStatus": config.schedule_status,
        },
        after={
            "activeVersionId": config.active_version_id,
            "scheduleStatus": "failed",
            "scheduledVersionId": version_id,
        },
        reason=reason,
    )
    return replace_model(
        state,
        model_configs=_upsert(state.model_configs, next_config, "config_id"),
        audits=(*state.audits, audit),
    ), {"config": next_config.model_dump(mode="json"), "version": _public_model(version)}
