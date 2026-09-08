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



def _allowed(actor: ActorContext, capability: str, requested: str | None, actual: str) -> bool:
    if requested not in {None, actual}:
        return False
    return actor.has_capability(capability)


def _upsert(items: tuple[Any, ...], item: Any, key: str) -> tuple[Any, ...]:
    identifier = getattr(item, key)
    kept = tuple(existing for existing in items if getattr(existing, key) != identifier)
    return (*kept, item)


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


def _baseline_prompt(now: datetime) -> tuple[PromptRecord, PromptVersion]:
    version_id = str(uuid.uuid4())
    version = PromptVersion(
        version_id=version_id,
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        version=short_version(SYSTEM_PROMPT),
        status="ACTIVE",
        template=SYSTEM_PROMPT,
        content_hash=content_hash(SYSTEM_PROMPT),
        input_schema_version="issue-extractor-input-v1",
        output_schema_version="issue-extractor-output-v1",
        taxonomy_version="imported-baseline",
        model_id="gemini-2.5-flash",
        created_by="system-baseline",
        created_at=now,
        submitted_by="system-baseline",
        submitted_at=now,
        approved_by="system-baseline",
        approved_at=now,
        activated_by="system-baseline",
        activated_at=now,
        change_reason="import code-based prompt as immutable baseline",
    )
    prompt = PromptRecord(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        component="issue-extractor",
        display_name="Issue Extractor",
        description="Splits user turns into classified IT issues",
        active_version_id=version_id,
        previous_healthy_version_id=version_id,
        etag=1,
    )
    return prompt, version


def _baseline_model(now: datetime) -> tuple[ModelConfigRecord, ModelConfigVersion]:
    version_id = str(uuid.uuid4())
    version = ModelConfigVersion(
        version_id=version_id,
        config_id="issue-extractor-model",
        provider="google_genai",
        model_id="gemini-2.5-flash",
        component="issue-extractor",
        status="ACTIVE",
        temperature=0.0,
        max_output_tokens=2048,
        timeout_seconds=30,
        retry=1,
        secret_ref="secret://gemini-api-key",
        region="asia-east1",
        pricing_version="v1",
        fallback_model_id="gemini-2.0-flash",
        fallback_on=("TIMEOUT", "UNAVAILABLE"),
        content_hash=content_hash("google_genai:gemini-2.5-flash"),
        created_by="system-baseline",
        created_at=now,
        approved_by="system-baseline",
        activated_by="system-baseline",
        activated_at=now,
        change_reason="import env model allowlist as baseline",
    )
    config = ModelConfigRecord(
        config_id="issue-extractor-model",
        component="issue-extractor",
        active_version_id=version_id,
        previous_healthy_version_id=version_id,
        etag=1,
    )
    return config, version


def _baseline_flags(now: datetime) -> tuple[list[FlagRecord], list[FlagVersion]]:
    flags: list[FlagRecord] = []
    versions: list[FlagVersion] = []
    for flag_id, spec in FLAG_CATALOG.items():
        version_id = str(uuid.uuid4())
        version = FlagVersion(
            version_id=version_id,
            flag_id=flag_id,
            status="ACTIVE",
            value=str(spec["default"]),
            environment="lab",
            effective_at=now,
            created_by="system-baseline",
            created_at=now,
            approved_by="system-baseline",
            activated_by="system-baseline",
            activated_at=now,
            change_reason="import existing runtime default",
        )
        flags.append(
            FlagRecord(
                flag_id=flag_id,
                description=spec["description"],
                owner=spec["owner"],
                flag_type=spec["flag_type"],
                safety_locked=bool(spec["safety_locked"]),
                default_value=str(spec["default"]),
                active_version_id=version_id,
                etag=1,
            )
        )
        versions.append(version)
    return flags, versions


def _verified_examples(examples: list[dict[str, Any]], dataset_version: str) -> list[dict[str, Any]]:
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
        topic_lines = [f"- Prioritize clarity and explicit escalation for: {t}" for t in unresolved_topics[:3]]
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
        raise GovernanceTransitionError("activation requires canary, or an emergency approved version")
    current = _active_prompt(state, prompt_id)
    retired = replace_model(current, status="RETIRED")
    updated = replace_model(
        version, status="ACTIVE", activated_by=actor.user_id, activated_at=now, change_reason=reason,
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
        prompt_versions=_upsert(_upsert(state.prompt_versions, retired, "version_id"), updated, "version_id"),
        audits=(*state.audits, audit),
    ), result


def _validate_model(
    provider: str, model_id: str, fallback_model_id: str | None, fallback_on: tuple[str, ...]
) -> None:
    allowed = PROVIDER_MODELS.get(provider)
    if allowed is None or model_id not in allowed:
        raise GovernanceValidationError("model is not on the provider allowlist")
    if fallback_model_id and (fallback_model_id not in allowed or fallback_model_id == model_id):
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
        version, status="APPROVED", approved_by=actor.user_id, approved_at=utc_now(), change_reason=reason,
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
    current = _find_model_version(state, config.active_version_id or "") if config.active_version_id else None
    retired = replace_model(current, status="RETIRED") if current else None
    updated = replace_model(
        version, status="ACTIVE", activated_by=actor.user_id, activated_at=now, change_reason=reason,
    )
    next_config = replace_model(
        config,
        active_version_id=version_id,
        previous_healthy_version_id=current.version_id if current else version_id,
        etag=config.etag + 1,
    )
    audit = replace_model(
        audit,
        before={"activeVersionId": current.version_id if current else None, "status": current.status if current else None},
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
        version, status="APPROVED", approved_by=actor.user_id, approved_at=utc_now(), change_reason=reason,
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
        next((item for item in state.flag_versions if item.version_id == flag.active_version_id), None)
        if flag.active_version_id
        else None
    )
    retired = replace_model(previous, status="RETIRED") if previous else None
    updated = replace_model(
        version, status="ACTIVE", activated_by=actor.user_id, activated_at=now, change_reason=reason,
    )
    next_flag = replace_model(flag, active_version_id=version_id, etag=flag.etag + 1)
    audit = replace_model(
        audit,
        before={"activeVersionId": flag.active_version_id, "value": previous.value if previous else None},
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
