"""Governance search hit collectors for SearchAuditMixin.search."""

from __future__ import annotations

from typing import Any

from operations_core.access import ActorContext

from .constants import READ
from .models import GovernanceState
from .service_helpers import _active_prompt, _allowed


def _status_matches(item_status: str, target_status: str | None) -> bool:
    if not target_status:
        return True
    return item_status.upper() == target_status


def _haystack_matches(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    return needle in haystack.casefold()


def _hit(
    *,
    type_name: str,
    item_id: str,
    title: str,
    snippet: str,
    status: str,
    owner_unit_id: Any = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": type_name,
        "id": item_id,
        "title": title,
        "snippet": snippet,
        "status": status,
    }
    if owner_unit_id is not None:
        result["owner_unit_id"] = owner_unit_id
    return result


def collect_catalog_hits(
    state: GovernanceState,
    *,
    actor: ActorContext,
    needle: str,
    target_status: str | None,
    doc_type: str | None,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for prompt in state.prompts:
        if not _allowed(actor, READ["prompt"], doc_type, "PROMPT"):
            continue
        active = _active_prompt(state, prompt.prompt_id)
        item_status = active.status if active else "ACTIVE"
        if not _status_matches(item_status, target_status):
            continue
        haystack = f"{prompt.prompt_id} {prompt.display_name} {active.version}"
        if not _haystack_matches(haystack, needle):
            continue
        hits.append(
            _hit(
                type_name="PROMPT",
                item_id=prompt.prompt_id,
                title=prompt.display_name,
                snippet=active.version,
                status=item_status,
            )
        )
    for flag in state.flags:
        if not _allowed(actor, READ["flag"], doc_type, "FLAG"):
            continue
        item_status = "ACTIVE" if flag.active_version_id else "DRAFT"
        if not _status_matches(item_status, target_status):
            continue
        haystack = f"{flag.flag_id} {flag.description}"
        if not _haystack_matches(haystack, needle):
            continue
        hits.append(
            _hit(
                type_name="FLAG",
                item_id=flag.flag_id,
                title=flag.flag_id,
                snippet=flag.description,
                status=item_status,
            )
        )
    for config in state.model_configs:
        if not _allowed(actor, READ["model"], doc_type, "MODEL"):
            continue
        item_status = "ACTIVE" if config.active_version_id else "DRAFT"
        if not _status_matches(item_status, target_status):
            continue
        haystack = f"{config.config_id} {config.component}"
        if not _haystack_matches(haystack, needle):
            continue
        hits.append(
            _hit(
                type_name="MODEL",
                item_id=config.config_id,
                title=config.component,
                snippet=config.config_id,
                status=item_status,
            )
        )
    return hits


def collect_policy_hits(
    state: GovernanceState,
    *,
    actor: ActorContext,
    needle: str,
    target_status: str | None,
    doc_type: str | None,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if actor.has_capability(READ["role"]) and doc_type in {None, "ROLE_MAPPING"}:
        for change in state.role_changes:
            item_status = str(change.status)
            if not _status_matches(item_status, target_status):
                continue
            haystack = f"{change.target_principal} {change.target_role or ''} {change.status}"
            if not _haystack_matches(haystack, needle):
                continue
            hits.append(
                _hit(
                    type_name="ROLE_MAPPING",
                    item_id=change.change_id,
                    title=change.target_principal,
                    snippet=change.status,
                    status=item_status,
                )
            )
    if actor.has_capability(READ["retention"]) and doc_type in {None, "RETENTION"}:
        for policy in state.retention_policies:
            item_status = str(policy.status)
            if not _status_matches(item_status, target_status):
                continue
            haystack = f"{policy.policy_id} {policy.migration_plan} {policy.status}"
            if not _haystack_matches(haystack, needle):
                continue
            hits.append(
                _hit(
                    type_name="RETENTION",
                    item_id=policy.version_id,
                    title=policy.policy_id,
                    snippet=f"ttl={policy.ttl_days} {policy.status}",
                    status=item_status,
                )
            )
    if actor.has_capability(READ["retention"]) and doc_type in {None, "MASKING"}:
        for policy in state.masking_policies:
            item_status = str(policy.status)
            if not _status_matches(item_status, target_status):
                continue
            haystack = f"{policy.policy_version} {policy.status}"
            if not _haystack_matches(haystack, needle):
                continue
            hits.append(
                _hit(
                    type_name="MASKING",
                    item_id=policy.version_id,
                    title=policy.policy_version,
                    snippet=policy.status,
                    status=item_status,
                )
            )
    return hits


def collect_audit_hits(
    state: GovernanceState,
    *,
    actor: ActorContext,
    needle: str,
    target_status: str | None,
    doc_type: str | None,
) -> list[dict[str, Any]]:
    if not (actor.has_capability(READ["audit"]) and doc_type in {None, "AUDIT"}):
        return []
    hits: list[dict[str, Any]] = []
    for event in state.audits:
        item_status = "SUCCESS" if getattr(event, "result", None) != "FAILED" else "FAILED"
        if not _status_matches(item_status, target_status):
            continue
        haystack = f"{event.action} {event.target_id}"
        if not _haystack_matches(haystack, needle):
            continue
        hits.append(
            _hit(
                type_name="AUDIT",
                item_id=event.audit_id,
                title=event.action,
                snippet=event.target_id,
                status=item_status,
            )
        )
    return hits


def collect_extra_document_hits(
    extra_documents: list[dict[str, Any]] | None,
    *,
    actor: ActorContext,
    needle: str,
    target_status: str | None,
    doc_type: str | None,
    owner_unit_id: str | None,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for document in extra_documents or ():
        required = str(document.get("requiredCapability") or "")
        actual_type = str(document.get("type") or "EXTERNAL")
        if doc_type not in {None, actual_type}:
            continue
        if (
            owner_unit_id
            and document.get("owner_unit_id")
            and document.get("owner_unit_id") != owner_unit_id
        ):
            continue
        if required and not actor.has_capability(required):
            continue
        item_status = str(document.get("status") or "ACTIVE")
        if not _status_matches(item_status, target_status):
            continue
        haystack = f"{document.get('title', '')} {document.get('snippet', '')}"
        if not _haystack_matches(haystack, needle):
            continue
        hits.append(
            _hit(
                type_name=actual_type,
                item_id=str(document.get("id") or ""),
                title=str(document.get("title") or ""),
                snippet=str(document.get("snippet") or ""),
                status=item_status,
                owner_unit_id=document.get("owner_unit_id"),
            )
        )
    return hits


def collect_search_hits(
    state: GovernanceState,
    *,
    actor: ActorContext,
    query: str,
    doc_type: str | None,
    owner_unit_id: str | None,
    status: str | None,
    extra_documents: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    needle = query.casefold()
    target_status = status.strip().upper() if status and status.strip() else None
    return [
        *collect_catalog_hits(
            state, actor=actor, needle=needle, target_status=target_status, doc_type=doc_type
        ),
        *collect_policy_hits(
            state, actor=actor, needle=needle, target_status=target_status, doc_type=doc_type
        ),
        *collect_audit_hits(
            state, actor=actor, needle=needle, target_status=target_status, doc_type=doc_type
        ),
        *collect_extra_document_hits(
            extra_documents,
            actor=actor,
            needle=needle,
            target_status=target_status,
            doc_type=doc_type,
            owner_unit_id=owner_unit_id,
        ),
    ]
