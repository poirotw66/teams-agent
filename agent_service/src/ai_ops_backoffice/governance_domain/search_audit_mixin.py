from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
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

class GovernanceSearchAuditMixin:
    def search(
        self,
        *,
        query: str,
        actor: ActorContext,
        doc_type: str | None = None,
        owner_unit_id: str | None = None,
        extra_documents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._require(actor, READ["search"])
        state = self._ensured()
        needle = query.casefold()
        hits: list[dict[str, Any]] = []
        for prompt in state.prompts:
            if not _allowed(actor, READ["prompt"], doc_type, "PROMPT"):
                continue
            active = _active_prompt(state, prompt.prompt_id)
            haystack = f"{prompt.prompt_id} {prompt.display_name} {active.version}"
            if needle and needle not in haystack.casefold():
                continue
            hits.append(
                {
                    "type": "PROMPT",
                    "id": prompt.prompt_id,
                    "title": prompt.display_name,
                    "snippet": active.version,
                }
            )
        for flag in state.flags:
            if not _allowed(actor, READ["flag"], doc_type, "FLAG"):
                continue
            haystack = f"{flag.flag_id} {flag.description}"
            if needle and needle not in haystack.casefold():
                continue
            hits.append(
                {
                    "type": "FLAG",
                    "id": flag.flag_id,
                    "title": flag.flag_id,
                    "snippet": flag.description,
                }
            )
        for config in state.model_configs:
            if not _allowed(actor, READ["model"], doc_type, "MODEL"):
                continue
            haystack = f"{config.config_id} {config.component}"
            if needle and needle not in haystack.casefold():
                continue
            hits.append(
                {
                    "type": "MODEL",
                    "id": config.config_id,
                    "title": config.component,
                    "snippet": config.config_id,
                }
            )
        if actor.has_capability(READ["role"]) and doc_type in {None, "ROLE_MAPPING"}:
            for change in state.role_changes:
                haystack = f"{change.target_principal} {change.target_role or ''} {change.status}"
                if needle and needle not in haystack.casefold():
                    continue
                hits.append(
                    {
                        "type": "ROLE_MAPPING",
                        "id": change.change_id,
                        "title": change.target_principal,
                        "snippet": change.status,
                    }
                )
        if actor.has_capability(READ["retention"]) and doc_type in {None, "RETENTION"}:
            for policy in state.retention_policies:
                haystack = f"{policy.policy_id} {policy.migration_plan} {policy.status}"
                if needle and needle not in haystack.casefold():
                    continue
                hits.append(
                    {
                        "type": "RETENTION",
                        "id": policy.version_id,
                        "title": policy.policy_id,
                        "snippet": f"ttl={policy.ttl_days} {policy.status}",
                    }
                )
        if actor.has_capability(READ["retention"]) and doc_type in {None, "MASKING"}:
            for policy in state.masking_policies:
                haystack = f"{policy.policy_version} {policy.status}"
                if needle and needle not in haystack.casefold():
                    continue
                hits.append(
                    {
                        "type": "MASKING",
                        "id": policy.version_id,
                        "title": policy.policy_version,
                        "snippet": policy.status,
                    }
                )
        if actor.has_capability(READ["audit"]) and doc_type in {None, "AUDIT"}:
            for event in state.audits:
                haystack = f"{event.action} {event.target_id}"
                if needle and needle not in haystack.casefold():
                    continue
                hits.append(
                    {
                        "type": "AUDIT",
                        "id": event.audit_id,
                        "title": event.action,
                        "snippet": event.target_id,
                    }
                )
        for document in extra_documents or ():
            required = str(document.get("requiredCapability") or "")
            actual_type = str(document.get("type") or "EXTERNAL")
            if doc_type not in {None, actual_type}:
                continue
            if owner_unit_id and document.get("owner_unit_id") and document.get("owner_unit_id") != owner_unit_id:
                continue
            if required and not actor.has_capability(required):
                continue
            haystack = f"{document.get('title', '')} {document.get('snippet', '')}"
            if needle and needle not in haystack.casefold():
                continue
            hits.append(
                {
                    "type": actual_type,
                    "id": str(document.get("id") or ""),
                    "title": str(document.get("title") or ""),
                    "snippet": str(document.get("snippet") or ""),
                    "owner_unit_id": document.get("owner_unit_id"),
                }
            )

        def operation(current: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            audit = self._audit(
                action="GOVERNANCE_SEARCH",
                actor=actor,
                target_type="SEARCH",
                target_id=doc_type or "ALL",
                after={"queryLength": len(query), "resultCount": len(hits)},
            )
            return replace_model(current, audits=(*current.audits, audit)), {
                "items": hits,
                "hits": hits,
                "count": len(hits),
            }

        return self._mutate(operation)

    def query_audit(
        self,
        *,
        actor: ActorContext,
        target_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._require(actor, READ["audit"])
        events = list(self._ensured().audits)
        if target_type:
            needle_target = target_type.strip().casefold()
            events = [item for item in events if needle_target in item.target_type.casefold()]
        if actor_id:
            needle_actor = actor_id.strip().casefold()
            events = [item for item in events if needle_actor in item.actor_id.casefold()]
        if action:
            needle_action = action.strip().casefold()
            events = [item for item in events if needle_action in item.action.casefold()]
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=UTC)
                events = [item for item in events if item.occurred_at >= start_dt]
            except Exception:
                pass
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=UTC)
                events = [item for item in events if item.occurred_at <= end_dt]
            except Exception:
                pass

        sorted_events = sorted(events, key=lambda e: e.occurred_at, reverse=True)
        start = int(cursor or "0")
        page = sorted_events[start : start + limit]
        next_index = start + len(page)
        next_cursor = str(next_index) if next_index < len(sorted_events) else None
        return {
            "items": [item.model_dump(mode="json") for item in page],
            "nextCursor": next_cursor,
            "hasMore": next_cursor is not None,
            "total": len(sorted_events),
        }

    def export_audit(
        self,
        *,
        actor: ActorContext,
        target_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        self._require(actor, READ["audit"])
        items = self.list_audit(
            actor=actor,
            target_type=target_type,
            actor_id=actor_id,
            action=action,
            start_date=start_date,
            end_date=end_date,
        )
        package = {
            "exportedAt": self._clock().isoformat(),
            "count": len(items),
            "targetType": target_type,
            "format": "json",
            "items": items,
        }

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            audit = self._audit(
                action="GOVERNANCE_AUDIT_EXPORTED",
                actor=actor,
                target_type="AUDIT",
                target_id=target_type or "ALL",
                after={"count": len(items)},
            )
            return replace_model(state, audits=(*state.audits, audit)), package

        return self._mutate(operation)

    def list_audit(
        self,
        *,
        actor: ActorContext,
        target_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require(actor, READ["audit"])
        res = self.query_audit(
            actor=actor,
            target_type=target_type,
            actor_id=actor_id,
            action=action,
            start_date=start_date,
            end_date=end_date,
            limit=limit or 10000,
            cursor=cursor,
        )
        return res["items"]
