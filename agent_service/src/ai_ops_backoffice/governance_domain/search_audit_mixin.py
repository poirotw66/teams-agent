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

class GovernanceSearchAuditMixin:
    def search(
        self,
        *,
        query: str,
        actor: ActorContext,
        doc_type: str | None = None,
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

    def export_audit(
        self,
        *,
        actor: ActorContext,
        target_type: str | None = None,
    ) -> dict[str, Any]:
        self._require(actor, READ["audit"])
        items = self.list_audit(actor=actor, target_type=target_type)
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

    def list_audit(self, *, actor: ActorContext, target_type: str | None = None) -> list[dict[str, Any]]:
        self._require(actor, READ["audit"])
        events = self._ensured().audits
        return [
            item.model_dump(mode="json")
            for item in events
            if target_type is None or item.target_type == target_type
        ]
