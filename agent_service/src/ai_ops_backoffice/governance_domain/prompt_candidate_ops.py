"""Prompt candidate creation, eval commit, and rollback operations."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from operations_core.access import ActorContext

from .errors import (
    GovernanceConflictError,
    GovernanceNotFoundError,
    GovernanceTransitionError,
)
from .helpers import (
    content_hash,
    fingerprint,
    public_prompt,
    replay,
    short_version,
    sticky_bucket,
    with_idempotency,
)
from .models import (
    EvalRun,
    GovernanceAuditEvent,
    GovernanceState,
    PromptVersion,
    replace_model,
)
from .service_helpers import (
    _active_prompt,
    _candidate_template,
    _find_prompt,
    _find_prompt_version,
    _upsert,
    _verified_examples,
)

AuditFactory = Callable[..., GovernanceAuditEvent]


def create_candidate_operation(
    state: GovernanceState,
    *,
    prompt_id: str,
    dataset_version: str,
    taxonomy_version: str,
    knowledge_release_id: str | None,
    verified_examples: list[dict[str, Any]],
    actor: ActorContext,
    idempotency_key: str | None,
    correlation_id: str | None,
    now: datetime,
    make_audit: AuditFactory,
) -> tuple[GovernanceState, dict[str, Any]]:
    selected = _verified_examples(verified_examples, dataset_version)
    payload = {
        "action": "PROMPT_CANDIDATE_CREATED",
        "promptId": prompt_id,
        "dataset": dataset_version,
        "examples": [item["text"] for item in selected],
    }
    request_fingerprint = fingerprint({"actorId": actor.user_id, **payload})
    replayed = replay(
        state,
        key=idempotency_key,
        action="PROMPT_CANDIDATE_CREATED",
        request_fingerprint=request_fingerprint,
    )
    if replayed is not None:
        return state, replayed
    prompt = _find_prompt(state, prompt_id)
    baseline = _active_prompt(state, prompt_id)
    template = _candidate_template(baseline.template, dataset_version, selected)
    version = PromptVersion(
        version_id=str(uuid.uuid4()),
        prompt_id=prompt_id,
        version=short_version(template),
        status="CANDIDATE",
        template=template,
        content_hash=content_hash(template),
        input_schema_version=baseline.input_schema_version,
        output_schema_version=baseline.output_schema_version,
        taxonomy_version=taxonomy_version,
        dataset_version=dataset_version,
        knowledge_release_id=knowledge_release_id,
        model_id=baseline.model_id,
        created_by=actor.user_id,
        created_at=now,
        submitted_by=actor.user_id,
        submitted_at=now,
        change_reason=f"generated from dataset {dataset_version}",
    )
    result = {
        "prompt": replace_model(prompt, etag=prompt.etag + 1).model_dump(mode="json"),
        "version": public_prompt(version, include_content=False),
    }
    audit = make_audit(
        action="PROMPT_CANDIDATE_CREATED",
        actor=actor,
        target_type="PROMPT",
        target_id=prompt_id,
        version_id=version.version_id,
        after={"contentHash": version.content_hash, "datasetVersion": dataset_version},
        correlation_id=correlation_id,
    )
    next_state = replace_model(
        state,
        prompts=_upsert(state.prompts, replace_model(prompt, etag=prompt.etag + 1), "prompt_id"),
        prompt_versions=(*state.prompt_versions, version),
        audits=(*state.audits, audit),
        idempotency=with_idempotency(
            state,
            key=idempotency_key,
            action="PROMPT_CANDIDATE_CREATED",
            request_fingerprint=request_fingerprint,
            result=result,
            created_at=now,
        ),
    )
    return next_state, result


def commit_prompt_eval(
    state: GovernanceState,
    *,
    prompt_id: str,
    version_id: str,
    snapshot: PromptVersion,
    run: EvalRun,
    actor: ActorContext,
    make_audit: AuditFactory,
) -> tuple[GovernanceState, dict[str, Any]]:
    current = _find_prompt_version(state, version_id)
    if current.prompt_id != prompt_id:
        raise GovernanceNotFoundError(version_id)
    if current.status not in {"CANDIDATE", "EVALUATED"}:
        raise GovernanceTransitionError("eval requires a candidate version")
    if current.content_hash != snapshot.content_hash:
        raise GovernanceConflictError("candidate changed during eval")
    if current.template != snapshot.template or current.model_id != snapshot.model_id:
        raise GovernanceConflictError("candidate binding changed during eval")
    updated = replace_model(current, status="EVALUATED", eval_run_id=run.run_id)
    audit = make_audit(
        action="PROMPT_EVALUATED",
        actor=actor,
        target_type="PROMPT",
        target_id=prompt_id,
        version_id=version_id,
        before={"status": current.status},
        after={
            "status": "EVALUATED",
            "criticalPassed": run.critical_passed,
            "qualityPassed": run.quality_passed,
        },
    )
    result = {
        "eval": run.model_dump(mode="json"),
        "version": public_prompt(updated, include_content=False),
    }
    return replace_model(
        state,
        prompt_versions=_upsert(state.prompt_versions, updated, "version_id"),
        eval_runs=(*state.eval_runs, run),
        audits=(*state.audits, audit),
    ), result


def rollback_prompt_operation(
    state: GovernanceState,
    *,
    prompt_id: str,
    reason: str,
    actor: ActorContext,
    now: datetime,
    make_audit: AuditFactory,
) -> tuple[GovernanceState, dict[str, Any]]:
    prompt = _find_prompt(state, prompt_id)
    if not prompt.previous_healthy_version_id:
        raise GovernanceTransitionError("no healthy version is available to rollback")
    previous = _find_prompt_version(state, prompt.previous_healthy_version_id)
    current = _active_prompt(state, prompt_id)
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
    audit = make_audit(
        action="PROMPT_ROLLED_BACK",
        actor=actor,
        target_type="PROMPT",
        target_id=prompt_id,
        version_id=previous.version_id,
        reason=reason,
        before={"activeVersionId": current.version_id},
        after={"activeVersionId": previous.version_id},
    )
    result = {
        "prompt": next_prompt.model_dump(mode="json"),
        "version": public_prompt(restored, include_content=False),
    }
    return replace_model(
        state,
        prompts=_upsert(state.prompts, next_prompt, "prompt_id"),
        prompt_versions=_upsert(
            _upsert(state.prompt_versions, failed, "version_id"), restored, "version_id"
        ),
        audits=(*state.audits, audit),
    ), result


def resolve_selected_prompt(
    state: GovernanceState,
    prompt_id: str,
    *,
    tenant: str,
    conversation_id: str,
) -> tuple[Any, Any]:
    prompt = _find_prompt(state, prompt_id)
    selected = _active_prompt(state, prompt_id)
    if prompt.canary_version_id:
        canary = _find_prompt_version(state, prompt.canary_version_id)
        if (
            not canary.canary_stopped
            and canary.canary_percent
            and sticky_bucket(tenant, conversation_id) < canary.canary_percent
        ):
            selected = canary
    return prompt, selected


def peek_runtime_selection(
    state: GovernanceState,
    prompt_id: str,
    *,
    tenant: str,
    conversation_id: str,
) -> dict[str, Any] | None:
    prompt = next((item for item in state.prompts if item.prompt_id == prompt_id), None)
    if prompt is None or not prompt.active_version_id:
        return None
    selected = _find_prompt_version(state, prompt.active_version_id)
    canary_selected = False
    if prompt.canary_version_id:
        canary = _find_prompt_version(state, prompt.canary_version_id)
        if (
            canary.status == "CANARY"
            and not canary.canary_stopped
            and canary.canary_percent
            and sticky_bucket(tenant, conversation_id) < canary.canary_percent
        ):
            selected = canary
            canary_selected = True
    if selected.status not in {"ACTIVE", "CANARY"}:
        return None
    if "{max_issues}" not in selected.template or "{faq_keys}" not in selected.template:
        return None
    return {
        "promptId": prompt_id,
        "versionId": selected.version_id,
        "version": selected.version,
        "contentHash": selected.content_hash,
        "template": selected.template,
        "canary": canary_selected,
        "stickyBucket": sticky_bucket(tenant, conversation_id),
    }
