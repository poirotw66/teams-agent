"""Feature-flag approve and activate transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from operations_core.access import ActorContext

from .errors import (
    GovernanceAuthorizationError,
    GovernanceNotFoundError,
    GovernanceTransitionError,
)
from .governance_state_ops import _upsert
from .models import GovernanceAuditEvent, GovernanceState, replace_model, utc_now


def _approve_flag(
    state: GovernanceState,
    flag_id: str,
    version_id: str,
    reason: str,
    actor: ActorContext,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    version = next((item for item in state.flag_versions if item.version_id == version_id), None)
    if version is None or version.flag_id != flag_id:
        raise GovernanceNotFoundError(version_id)
    if version.created_by == actor.user_id:
        raise GovernanceAuthorizationError("submitter cannot approve their own flag candidate")
    if version.status != "CANDIDATE":
        raise GovernanceTransitionError("flag is not awaiting approval")
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
        flag_versions=_upsert(state.flag_versions, updated, "version_id"),
        audits=(*state.audits, audit),
    ), {"version": updated.model_dump(mode="json")}


def _activate_flag(
    state: GovernanceState,
    flag_id: str,
    version_id: str,
    reason: str,
    actor: ActorContext,
    now: datetime,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    flag = next((item for item in state.flags if item.flag_id == flag_id), None)
    version = next((item for item in state.flag_versions if item.version_id == version_id), None)
    if flag is None or version is None:
        raise GovernanceNotFoundError(version_id)
    if version.status != "APPROVED":
        raise GovernanceTransitionError("flag activation requires approval")
    previous = (
        next(
            (item for item in state.flag_versions if item.version_id == flag.active_version_id),
            None,
        )
        if flag.active_version_id
        else None
    )
    retired = replace_model(previous, status="RETIRED") if previous else None
    updated = replace_model(
        version,
        status="ACTIVE",
        activated_by=actor.user_id,
        activated_at=now,
        change_reason=reason,
    )
    next_flag = replace_model(flag, active_version_id=version_id, etag=flag.etag + 1)
    audit = replace_model(
        audit,
        before={
            "activeVersionId": flag.active_version_id,
            "value": previous.value if previous else None,
        },
        after={"activeVersionId": version_id, "value": updated.value, "status": "ACTIVE"},
    )
    versions = state.flag_versions
    if retired is not None:
        versions = _upsert(versions, retired, "version_id")
    return replace_model(
        state,
        flags=_upsert(state.flags, next_flag, "flag_id"),
        flag_versions=_upsert(versions, updated, "version_id"),
        audits=(*state.audits, audit),
    ), {"flag": next_flag.model_dump(mode="json"), "version": updated.model_dump(mode="json")}
