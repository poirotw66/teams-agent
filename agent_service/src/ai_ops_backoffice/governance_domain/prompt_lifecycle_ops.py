"""Prompt lookup, candidate drafting, and approve/activate transitions."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from operations_core.access import ActorContext

from .constants import MAX_PROMPT_LENGTH
from .errors import (
    GovernanceAuthorizationError,
    GovernanceNotFoundError,
    GovernanceTransitionError,
    GovernanceValidationError,
)
from .governance_state_ops import _upsert
from .helpers import public_prompt, reject_secrets_and_injection
from .models import (
    EvalRun,
    GovernanceAuditEvent,
    GovernanceState,
    PromptRecord,
    PromptVersion,
    replace_model,
    utc_now,
)


def _find_prompt(state: GovernanceState, prompt_id: str) -> PromptRecord:
    prompt = next((item for item in state.prompts if item.prompt_id == prompt_id), None)
    if prompt is None:
        raise GovernanceNotFoundError(prompt_id)
    return prompt


def _find_prompt_version(state: GovernanceState, version_id: str) -> PromptVersion:
    version = next((item for item in state.prompt_versions if item.version_id == version_id), None)
    if version is None:
        raise GovernanceNotFoundError(version_id)
    return version


def _active_prompt(state: GovernanceState, prompt_id: str) -> PromptVersion:
    prompt = _find_prompt(state, prompt_id)
    if not prompt.active_version_id:
        raise GovernanceNotFoundError(prompt_id)
    return _find_prompt_version(state, prompt.active_version_id)


def _verified_examples(
    examples: list[dict[str, Any]], dataset_version: str
) -> list[dict[str, Any]]:
    selected = [
        item
        for item in examples
        if item.get("status") == "VERIFIED" and item.get("dataset_version") == dataset_version
    ]
    if not selected:
        raise GovernanceValidationError("dataset version has no VERIFIED examples")
    for item in selected:
        reject_secrets_and_injection(str(item.get("text") or ""), label="dataset")
    return selected


def _candidate_template(baseline: str, dataset_version: str, examples: list[dict[str, Any]]) -> str:
    counts = Counter((str(item["expected_route"]), str(item["label"])) for item in examples)
    guidance_lines = [
        f"- {route} {label}: {count} verified examples"
        for (route, label), count in sorted(counts.items())
    ]

    failure_patterns: Counter[str] = Counter()
    unresolved_topics: list[str] = []
    for item in examples:
        reason = str(item.get("failure_reason") or item.get("reason") or "").strip()
        if reason and reason.lower() not in {"none", "null", "n/a", "ok"}:
            failure_patterns[reason] += 1
        label = str(item.get("label") or "").lower()
        if "negative" in label or "unresolved" in label or item.get("resolved") is False:
            text = str(item.get("text") or "").strip()
            if text and len(text) <= 80 and text not in unresolved_topics:
                unresolved_topics.append(text)

    refinement_sections = []
    if failure_patterns:
        pattern_lines = [
            f"- Address failure pattern '{pat}': verify domain boundaries before answering ({cnt} cases)"
            for pat, cnt in failure_patterns.most_common(5)
        ]
        refinement_sections.append("Failure mitigation instructions:\n" + "\n".join(pattern_lines))

    if unresolved_topics:
        topic_lines = [
            f"- Prioritize clarity and explicit escalation for: {t}" for t in unresolved_topics[:3]
        ]
        refinement_sections.append("Unresolved query safeguards:\n" + "\n".join(topic_lines))

    guidance_str = "\n".join(guidance_lines)
    if refinement_sections:
        guidance_str += "\n\n" + "\n\n".join(refinement_sections)

    template = f"{baseline}\n\nVerified dataset guidance ({dataset_version}):\n{guidance_str}\n"
    reject_secrets_and_injection(template, label="candidate")
    if "{max_issues}" not in template or "{faq_keys}" not in template:
        raise GovernanceValidationError("candidate failed prompt schema inspection")
    if len(template) > MAX_PROMPT_LENGTH:
        raise GovernanceValidationError("candidate exceeds maximum prompt length")
    return template


def _eval_for(state: GovernanceState, run_id: str | None) -> EvalRun | None:
    if not run_id:
        return None
    return next((item for item in state.eval_runs if item.run_id == run_id), None)


def _approve_prompt(
    state: GovernanceState,
    *,
    prompt_id: str,
    version_id: str,
    reason: str,
    actor: ActorContext,
    policy_exception_reason: str | None,
    policy_exception_expires_at: datetime | None,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    version = _find_prompt_version(state, version_id)
    if version.prompt_id != prompt_id:
        raise GovernanceNotFoundError(version_id)
    if version.status != "EVALUATED":
        raise GovernanceTransitionError("approval requires a completed eval")
    if version.submitted_by == actor.user_id:
        raise GovernanceAuthorizationError("submitter cannot approve their own candidate")
    run = _eval_for(state, version.eval_run_id)
    if run is None or not run.critical_passed:
        raise GovernanceTransitionError("critical safety tests must pass before approval")
    if not run.quality_passed and not policy_exception_reason:
        raise GovernanceTransitionError("quality gate failed; a dated policy exception is required")
    updated = replace_model(
        version,
        status="APPROVED",
        approved_by=actor.user_id,
        approved_at=utc_now(),
        change_reason=reason,
        policy_exception_reason=policy_exception_reason,
        policy_exception_expires_at=policy_exception_expires_at,
    )
    audit = replace_model(
        audit,
        before={"status": version.status},
        after={
            "status": "APPROVED",
            "approvedBy": actor.user_id,
            "policyExceptionReason": policy_exception_reason,
        },
    )
    result = {"version": public_prompt(updated, include_content=False)}
    return replace_model(
        state,
        prompt_versions=_upsert(state.prompt_versions, updated, "version_id"),
        audits=(*state.audits, audit),
    ), result


def _activate_prompt(
    state: GovernanceState,
    *,
    prompt_id: str,
    version_id: str,
    reason: str,
    actor: ActorContext,
    emergency: bool,
    now: datetime,
    audit: GovernanceAuditEvent,
) -> tuple[GovernanceState, dict[str, Any]]:
    prompt = _find_prompt(state, prompt_id)
    version = _find_prompt_version(state, version_id)
    allowed = version.status == "CANARY" or (emergency and version.status == "APPROVED")
    if not allowed:
        raise GovernanceTransitionError(
            "activation requires canary, or an emergency approved version"
        )
    current = _active_prompt(state, prompt_id)
    retired = replace_model(current, status="RETIRED")
    updated = replace_model(
        version,
        status="ACTIVE",
        activated_by=actor.user_id,
        activated_at=now,
        change_reason=reason,
    )
    next_prompt = replace_model(
        prompt,
        active_version_id=version_id,
        canary_version_id=None,
        previous_healthy_version_id=current.version_id,
        etag=prompt.etag + 1,
    )
    audit = replace_model(
        audit,
        before={"activeVersionId": current.version_id, "status": current.status},
        after={
            "activeVersionId": version_id,
            "status": "ACTIVE",
            "activatedBy": actor.user_id,
        },
    )
    result = {
        "prompt": next_prompt.model_dump(mode="json"),
        "version": public_prompt(updated, include_content=False),
    }
    return replace_model(
        state,
        prompts=_upsert(state.prompts, next_prompt, "prompt_id"),
        prompt_versions=_upsert(
            _upsert(state.prompt_versions, retired, "version_id"), updated, "version_id"
        ),
        audits=(*state.audits, audit),
    ), result
