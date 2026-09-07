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

class GovernancePromptsMixin:
    def list_prompts(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["prompt"])
        state = self._ensured()
        include = actor.has_capability(READ["prompt_content"])
        return [
            {
                "prompt": item.model_dump(mode="json"),
                "active": public_prompt(_active_prompt(state, item.prompt_id), include_content=include)
                if item.active_version_id
                else None,
            }
            for item in state.prompts
        ]

    def prompt_detail(self, prompt_id: str, *, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, READ["prompt"])
        state = self._ensured()
        prompt = _find_prompt(state, prompt_id)
        include = actor.has_capability(READ["prompt_content"])
        versions = [item for item in state.prompt_versions if item.prompt_id == prompt_id]
        return {
            "prompt": prompt.model_dump(mode="json"),
            "versions": [public_prompt(item, include_content=include) for item in versions],
        }

    def prompt_diff(self, prompt_id: str, version_id: str, *, actor: ActorContext) -> dict[str, Any]:
        detail = self.prompt_detail(prompt_id, actor=actor)
        include = actor.has_capability(READ["prompt_content"])
        state = self._ensured()
        candidate = _find_prompt_version(state, version_id)
        baseline = _active_prompt(state, prompt_id)
        diff = None
        if include:
            import difflib

            diff = "\n".join(
                difflib.unified_diff(
                    baseline.template.splitlines(),
                    candidate.template.splitlines(),
                    fromfile="active",
                    tofile="candidate",
                    lineterm="",
                )
            )
        return {
            "active": public_prompt(baseline, include_content=include),
            "candidate": public_prompt(candidate, include_content=include),
            "activeUnchanged": baseline.version_id == _find_prompt(state, prompt_id).active_version_id,
            "diff": diff,
            "eval": next(
                (item.model_dump(mode="json") for item in state.eval_runs if item.run_id == candidate.eval_run_id),
                None,
            ),
            "prompt": detail["prompt"],
        }

    def create_prompt_candidate(
        self,
        *,
        prompt_id: str,
        dataset_version: str,
        taxonomy_version: str,
        knowledge_release_id: str | None,
        verified_examples: list[dict[str, Any]],
        actor: ActorContext,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["prompt_candidate"])
        selected = _verified_examples(verified_examples, dataset_version)
        payload = {
            "action": "PROMPT_CANDIDATE_CREATED",
            "promptId": prompt_id,
            "dataset": dataset_version,
            "examples": [item["text"] for item in selected],
        }
        request_fingerprint = fingerprint({"actorId": actor.user_id, **payload})

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            replayed = replay(
                state, key=idempotency_key, action="PROMPT_CANDIDATE_CREATED",
                request_fingerprint=request_fingerprint,
            )
            if replayed is not None:
                return state, replayed
            prompt = _find_prompt(state, prompt_id)
            baseline = _active_prompt(state, prompt_id)
            template = _candidate_template(baseline.template, dataset_version, selected)
            now = self._clock()
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
            audit = self._audit(
                action="PROMPT_CANDIDATE_CREATED", actor=actor, target_type="PROMPT",
                target_id=prompt_id, version_id=version.version_id,
                after={"contentHash": version.content_hash, "datasetVersion": dataset_version},
                correlation_id=correlation_id,
            )
            next_state = replace_model(
                state,
                prompts=_upsert(state.prompts, replace_model(prompt, etag=prompt.etag + 1), "prompt_id"),
                prompt_versions=(*state.prompt_versions, version),
                audits=(*state.audits, audit),
                idempotency=with_idempotency(
                    state, key=idempotency_key, action="PROMPT_CANDIDATE_CREATED",
                    request_fingerprint=request_fingerprint, result=result, created_at=now,
                ),
            )
            return next_state, result

        return self._mutate(operation)

    async def run_prompt_eval(
        self,
        *,
        prompt_id: str,
        version_id: str,
        verified_examples: list[dict[str, Any]],
        actor: ActorContext,
    ) -> dict[str, Any]:
        """Run eval outside the governance mutation, then commit the result.

        Model / Agent execution must not hold a long transaction. Snapshot the
        candidate first, evaluate asynchronously, then verify the version is
        unchanged before persisting the EvalRun.
        """
        self._require(actor, WRITE["prompt_eval"])
        state = self._ensured()
        version = _find_prompt_version(state, version_id)
        if version.prompt_id != prompt_id:
            raise GovernanceNotFoundError(version_id)
        if version.status not in {"CANDIDATE", "EVALUATED"}:
            raise GovernanceTransitionError("eval requires a candidate version")
        selected = _verified_examples(verified_examples, version.dataset_version or "")
        baseline = _active_prompt(state, prompt_id)

        run = await evaluate_prompt_async(
            candidate=version,
            baseline=baseline,
            examples=selected,
            actor_id=actor.user_id,
            taxonomy_version=version.taxonomy_version,
            knowledge_release_id=version.knowledge_release_id,
            flow_harness=self._eval_flow_harness,
        )

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            current = _find_prompt_version(state, version_id)
            if current.prompt_id != prompt_id:
                raise GovernanceNotFoundError(version_id)
            if current.status not in {"CANDIDATE", "EVALUATED"}:
                raise GovernanceTransitionError("eval requires a candidate version")
            if current.content_hash != version.content_hash:
                raise GovernanceConflictError("candidate changed during eval")
            if current.template != version.template or current.model_id != version.model_id:
                raise GovernanceConflictError("candidate binding changed during eval")
            updated = replace_model(current, status="EVALUATED", eval_run_id=run.run_id)
            audit = self._audit(
                action="PROMPT_EVALUATED", actor=actor, target_type="PROMPT",
                target_id=prompt_id, version_id=version_id,
                before={"status": current.status},
                after={"status": "EVALUATED", "criticalPassed": run.critical_passed, "qualityPassed": run.quality_passed},
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

        return self._mutate(operation)

    def approve_prompt(
        self,
        *,
        prompt_id: str,
        version_id: str,
        reason: str,
        actor: ActorContext,
        policy_exception_reason: str | None = None,
        policy_exception_expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["prompt_approve"])
        return self._mutate(
            lambda state: _approve_prompt(
                state, prompt_id=prompt_id, version_id=version_id, reason=reason, actor=actor,
                policy_exception_reason=policy_exception_reason,
                policy_exception_expires_at=policy_exception_expires_at,
                audit=self._audit(
                    action="PROMPT_APPROVED", actor=actor, target_type="PROMPT",
                    target_id=prompt_id, version_id=version_id, reason=reason,
                ),
            )
        )

    def start_prompt_canary(
        self,
        *,
        prompt_id: str,
        version_id: str,
        percent: int,
        environment: str,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["prompt_canary"])
        if percent < 1 or percent > 99:
            raise GovernanceValidationError("production canary must be a percentage between 1 and 99")

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            prompt = _find_prompt(state, prompt_id)
            version = _find_prompt_version(state, version_id)
            if version.status != "APPROVED":
                raise GovernanceTransitionError("canary requires an approved version")
            updated = replace_model(
                version, status="CANARY", canary_percent=percent, canary_environment=environment,
                canary_stopped=False, change_reason=reason,
            )
            next_prompt = replace_model(
                prompt, canary_version_id=version_id, etag=prompt.etag + 1,
            )
            audit = self._audit(
                action="PROMPT_CANARY_STARTED", actor=actor, target_type="PROMPT",
                target_id=prompt_id, version_id=version_id, reason=reason,
                before={"status": version.status, "canaryVersionId": prompt.canary_version_id},
                after={"status": "CANARY", "percent": percent, "environment": environment, "canaryVersionId": version_id},
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

        return self._mutate(operation)

    def activate_prompt(
        self,
        *,
        prompt_id: str,
        version_id: str,
        reason: str,
        actor: ActorContext,
        emergency: bool = False,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["prompt_activate"])
        return self._mutate(
            lambda state: _activate_prompt(
                state, prompt_id=prompt_id, version_id=version_id, reason=reason,
                actor=actor, emergency=emergency, now=self._clock(),
                audit=self._audit(
                    action="PROMPT_ACTIVATED", actor=actor, target_type="PROMPT",
                    target_id=prompt_id, version_id=version_id, reason=reason,
                ),
            )
        )

    def rollback_prompt(self, *, prompt_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["prompt_rollback"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            prompt = _find_prompt(state, prompt_id)
            if not prompt.previous_healthy_version_id:
                raise GovernanceTransitionError("no healthy version is available to rollback")
            previous = _find_prompt_version(state, prompt.previous_healthy_version_id)
            current = _active_prompt(state, prompt_id)
            now = self._clock()
            failed = replace_model(current, status="RETIRED", change_reason=reason)
            restored = replace_model(
                previous, status="ACTIVE", activated_by=actor.user_id, activated_at=now,
                rollback_of_version_id=current.version_id, change_reason=reason,
            )
            next_prompt = replace_model(
                prompt,
                active_version_id=previous.version_id,
                canary_version_id=None,
                previous_healthy_version_id=previous.version_id,
                etag=prompt.etag + 1,
            )
            audit = self._audit(
                action="PROMPT_ROLLED_BACK", actor=actor, target_type="PROMPT",
                target_id=prompt_id, version_id=previous.version_id, reason=reason,
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

        return self._mutate(operation)

    def resolve_prompt(
        self,
        prompt_id: str,
        *,
        tenant: str,
        conversation_id: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._require(actor, READ["prompt"])
        state = self._ensured()
        prompt = _find_prompt(state, prompt_id)
        selected = _active_prompt(state, prompt_id)
        canary = None
        if prompt.canary_version_id:
            canary = _find_prompt_version(state, prompt.canary_version_id)
            if (
                not canary.canary_stopped
                and canary.canary_percent
                and sticky_bucket(tenant, conversation_id) < canary.canary_percent
            ):
                selected = canary
        include = actor.has_capability(READ["prompt_content"])
        return {
            "promptId": prompt_id,
            "stickyBucket": sticky_bucket(tenant, conversation_id),
            "selected": public_prompt(selected, include_content=include),
        }

    def peek_runtime_prompt(
        self,
        prompt_id: str,
        *,
        tenant: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """Read-only Agent runtime pointer. Never seeds or mutates governance state."""
        state = self._repository.load()
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

    def stop_prompt_canary(
        self,
        *,
        prompt_id: str,
        reason: str,
        actor: ActorContext,
        rollback: bool = False,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["prompt_canary"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
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
                self._audit(
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
                current = _active_prompt(state, prompt_id)
                previous = _find_prompt_version(state, prompt.previous_healthy_version_id)
                now = self._clock()
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
                    self._audit(
                        action="PROMPT_CANARY_AUTO_ROLLBACK",
                        actor=actor,
                        target_type="PROMPT",
                        target_id=prompt_id,
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
                    prompt_versions=_upsert(
                        _upsert(versions, failed, "version_id"), restored, "version_id"
                    ),
                    audits=(*state.audits, *audits),
                ), result
            next_prompt = replace_model(
                prompt, canary_version_id=None, etag=prompt.etag + 1
            )
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

        return self._mutate(operation)

    def evaluate_prompt_canary(
        self,
        *,
        prompt_id: str,
        error_rate: float,
        negative_feedback_rate: float,
        handoff_rate: float,
        safety_alerts: int,
        sample_size: int,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["prompt_canary"])
        # Critical safety always wins — never wait for sample size.
        if safety_alerts > 0:
            stopped = self.stop_prompt_canary(
                prompt_id=prompt_id,
                reason="critical safety alert during canary",
                actor=actor,
                rollback=False,
            )
            return {**stopped, "reason": "critical safety alert"}
        if sample_size < 10:
            return {
                "action": "CONTINUE",
                "reason": "insufficient sample size",
                "promptId": prompt_id,
            }
        if error_rate >= 0.15 or negative_feedback_rate >= 0.25 or handoff_rate >= 0.4:
            stopped = self.stop_prompt_canary(
                prompt_id=prompt_id,
                reason="canary stop thresholds exceeded",
                actor=actor,
                rollback=False,
            )
            return {**stopped, "reason": "quality or availability regression"}
        return {
            "action": "CONTINUE",
            "reason": "within thresholds",
            "promptId": prompt_id,
        }
