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


class GovernanceService:
    """Phase 3 governed release lifecycle for prompts, models, flags, and access."""

    def __init__(
        self,
        repository: GovernanceRepository,
        *,
        clock: Clock | None = None,
        eval_flow_harness: PromptFlowHarness | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or utc_now
        self._eval_flow_harness = eval_flow_harness

    def _require(self, actor: ActorContext, capability: str) -> None:
        if actor.user_id in self._repository.load().revoked_principals:
            raise GovernanceAuthorizationError("principal access has been revoked")
        if not actor.has_capability(capability):
            raise GovernanceAuthorizationError(f"missing capability {capability}")

    def _audit(
        self,
        *,
        action: str,
        actor: ActorContext,
        target_type: str,
        target_id: str,
        version_id: str | None = None,
        reason: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> GovernanceAuditEvent:
        return GovernanceAuditEvent(
            audit_id=str(uuid.uuid4()),
            action=action,
            actor_id=actor.user_id,
            actor_role=actor.role,
            target_type=target_type,  # type: ignore[arg-type]
            target_id=target_id,
            version_id=version_id,
            reason=reason,
            before=redact_secrets(before) if before else None,
            after=redact_secrets(after) if after else None,
            correlation_id=correlation_id,
            occurred_at=self._clock(),
        )

    def _seed(self, state: GovernanceState) -> GovernanceState:
        if state.prompts:
            return state
        now = self._clock()
        prompt, version = _baseline_prompt(now)
        model, model_version = _baseline_model(now)
        flags, flag_versions = _baseline_flags(now)
        masking = MaskingPolicyVersion(
            version_id=str(uuid.uuid4()),
            policy_version=MASKING_POLICY_VERSION,
            status="ACTIVE",
            rules_hash=resolve_masking_pack(MASKING_POLICY_VERSION).rules_hash,
            created_by="system-baseline",
            created_at=now,
            approved_by="system-baseline",
            activated_by="system-baseline",
            activated_at=now,
            change_reason="import code-based masking policy",
        )
        retention = RetentionPolicyVersion(
            version_id=str(uuid.uuid4()),
            policy_id="operational-events",
            status="ACTIVE",
            ttl_days=365,
            migration_plan="baseline import; no TTL change",
            created_by="system-baseline",
            created_at=now,
            approved_by="system-baseline",
            activated_by="system-baseline",
            activated_at=now,
            change_reason="import existing retention baseline",
        )
        return replace_model(
            state,
            prompts=(prompt,),
            prompt_versions=(version,),
            model_configs=(model,),
            model_versions=(model_version,),
            flags=tuple(flags),
            flag_versions=tuple(flag_versions),
            masking_policies=(masking,),
            retention_policies=(retention,),
        )

    def _mutate(self, operation: Callable[[GovernanceState], tuple[GovernanceState, dict[str, Any]]]) -> dict[str, Any]:
        def wrapped(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            seeded = self._seed(state)
            next_state, result = operation(seeded)
            return replace_model(next_state, revision=seeded.revision + 1), result

        return self._repository.mutate(wrapped)

    def _ensured(self) -> GovernanceState:
        loaded = self._repository.load()
        if loaded.prompts:
            return loaded
        self._mutate(lambda state: (state, {"seeded": True}))
        return self._repository.load()

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
                after={"criticalPassed": run.critical_passed, "qualityPassed": run.quality_passed},
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
                after={"percent": percent, "environment": environment},
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

    def peek_runtime_model(self, config_id: str) -> dict[str, Any] | None:
        """Read-only active model pointer for Agent runtime."""
        state = self._repository.load()
        config = next((item for item in state.model_configs if item.config_id == config_id), None)
        if config is None or not config.active_version_id:
            return None
        version = _find_model_version(state, config.active_version_id)
        if version.status != "ACTIVE":
            return None
        return {
            "configId": config_id,
            "versionId": version.version_id,
            "provider": version.provider,
            "modelId": version.model_id,
            "secretRef": version.secret_ref,
            "fallbackModelId": version.fallback_model_id,
            "fallbackOn": list(version.fallback_on),
        }

    def peek_runtime_flag(
        self, flag_id: str, *, environment: str = "lab"
    ) -> dict[str, Any] | None:
        """Read-only effective flag value with expiry-safe defaults."""
        from .constants import FLAG_CATALOG

        catalog = FLAG_CATALOG.get(flag_id)
        if catalog is None:
            return None
        state = self._repository.load()
        flag = next((item for item in state.flags if item.flag_id == flag_id), None)
        if flag is None:
            return {
                "flagId": flag_id,
                "value": str(catalog["default"]),
                "source": "catalog_default",
                "safetyLocked": bool(catalog["safety_locked"]),
            }
        value = flag.default_value
        source = "flag_default"
        if flag.active_version_id:
            version = next(
                (item for item in state.flag_versions if item.version_id == flag.active_version_id),
                None,
            )
            if version is not None and version.status == "ACTIVE":
                expired = version.expires_at is not None and version.expires_at <= self._clock()
                if version.environment == environment and not expired:
                    value = version.value
                    source = "active_version"
                elif expired:
                    value = flag.default_value
                    source = "expired_default"
        if flag.safety_locked and value.lower() in {"false", "disabled"}:
            value = str(catalog["default"])
            source = "safety_locked_default"
        return {
            "flagId": flag_id,
            "value": value,
            "source": source,
            "safetyLocked": flag.safety_locked,
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

    def peek_runtime_retention(self, policy_id: str = "operational-events") -> dict[str, Any] | None:
        """Read-only ACTIVE retention TTL for ops runtime."""
        state = self._repository.load()
        active = next(
            (
                item
                for item in state.retention_policies
                if item.policy_id == policy_id and item.status == "ACTIVE"
            ),
            None,
        )
        if active is None:
            return None
        return {
            "policyId": active.policy_id,
            "versionId": active.version_id,
            "ttlDays": active.ttl_days,
            "status": active.status,
        }

    def peek_runtime_masking(self) -> dict[str, Any] | None:
        """Read-only ACTIVE masking policy version for ops runtime."""
        state = self._repository.load()
        active = next(
            (item for item in state.masking_policies if item.status == "ACTIVE"),
            None,
        )
        if active is None:
            return None
        return {
            "versionId": active.version_id,
            "policyVersion": active.policy_version,
            "rulesHash": active.rules_hash,
            "status": active.status,
        }

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

    def create_model_candidate(
        self,
        *,
        config_id: str,
        provider: str,
        model_id: str,
        component: str,
        temperature: float,
        max_output_tokens: int,
        timeout_seconds: int,
        retry: int,
        secret_ref: str,
        region: str,
        pricing_version: str,
        fallback_model_id: str | None,
        fallback_on: tuple[str, ...],
        actor: ActorContext,
        change_reason: str,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["model_write"])
        _validate_model(provider, model_id, fallback_model_id, fallback_on)
        secret_ref = require_secret_ref(secret_ref)

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            now = self._clock()
            config = next((item for item in state.model_configs if item.config_id == config_id), None)
            if config is None:
                config = ModelConfigRecord(config_id=config_id, component=component, etag=1)
            hashed = content_hash(f"{provider}:{model_id}:{temperature}:{secret_ref}:{fallback_model_id}")
            version = ModelConfigVersion(
                version_id=str(uuid.uuid4()),
                config_id=config_id,
                provider=provider,
                model_id=model_id,
                component=component,
                status="CANDIDATE",
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout_seconds=timeout_seconds,
                retry=retry,
                secret_ref=secret_ref,
                region=region,
                pricing_version=pricing_version,
                fallback_model_id=fallback_model_id,
                fallback_on=fallback_on,
                content_hash=hashed,
                created_by=actor.user_id,
                created_at=now,
                change_reason=change_reason,
            )
            audit = self._audit(
                action="MODEL_CANDIDATE_CREATED", actor=actor, target_type="MODEL",
                target_id=config_id, version_id=version.version_id, reason=change_reason,
                after=_public_model(version),
            )
            next_config = replace_model(config, etag=config.etag + 1)
            result = {"config": next_config.model_dump(mode="json"), "version": _public_model(version)}
            return replace_model(
                state,
                model_configs=_upsert(state.model_configs, next_config, "config_id"),
                model_versions=(*state.model_versions, version),
                audits=(*state.audits, audit),
            ), result

        return self._mutate(operation)

    def run_model_eval(self, *, config_id: str, version_id: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["model_write"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = _find_model_version(state, version_id)
            if version.config_id != config_id:
                raise GovernanceNotFoundError(version_id)
            run = evaluate_model(version=version, actor_id=actor.user_id)
            updated = replace_model(version, status="EVALUATED", eval_run_id=run.run_id)
            audit = self._audit(
                action="MODEL_EVALUATED", actor=actor, target_type="MODEL",
                target_id=config_id, version_id=version_id,
                after={"criticalPassed": run.critical_passed},
            )
            return replace_model(
                state,
                model_versions=_upsert(state.model_versions, updated, "version_id"),
                eval_runs=(*state.eval_runs, run),
                audits=(*state.audits, audit),
            ), {"eval": run.model_dump(mode="json"), "version": _public_model(updated)}

        return self._mutate(operation)

    def approve_model(self, *, config_id: str, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["model_approve"])
        return self._mutate(lambda state: _approve_model(state, config_id, version_id, reason, actor, self._audit(
            action="MODEL_APPROVED", actor=actor, target_type="MODEL",
            target_id=config_id, version_id=version_id, reason=reason,
        )))

    def activate_model(self, *, config_id: str, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["model_activate"])
        return self._mutate(lambda state: _activate_model(
            state, config_id, version_id, reason, actor, self._clock(),
            self._audit(
                action="MODEL_ACTIVATED", actor=actor, target_type="MODEL",
                target_id=config_id, version_id=version_id, reason=reason,
            ),
        ))

    def rollback_model(self, *, config_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["model_activate"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            config = _find_model(state, config_id)
            if not config.previous_healthy_version_id:
                raise GovernanceTransitionError("no healthy model version is available to rollback")
            previous = _find_model_version(state, config.previous_healthy_version_id)
            current = _find_model_version(state, config.active_version_id or "")
            now = self._clock()
            restored = replace_model(previous, status="ACTIVE", activated_by=actor.user_id, activated_at=now)
            failed = replace_model(current, status="RETIRED", change_reason=reason)
            next_config = replace_model(
                config, active_version_id=previous.version_id, etag=config.etag + 1,
            )
            audit = self._audit(
                action="MODEL_ROLLED_BACK", actor=actor, target_type="MODEL",
                target_id=config_id, version_id=previous.version_id, reason=reason,
            )
            return replace_model(
                state,
                model_configs=_upsert(state.model_configs, next_config, "config_id"),
                model_versions=_upsert(
                    _upsert(state.model_versions, failed, "version_id"), restored, "version_id"
                ),
                audits=(*state.audits, audit),
            ), {"config": next_config.model_dump(mode="json"), "version": _public_model(restored)}

        return self._mutate(operation)

    def simulate_fallback(self, *, config_id: str, error: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, READ["model"])
        state = self._ensured()
        config = _find_model(state, config_id)
        active = _find_model_version(state, config.active_version_id or "")
        if error not in active.fallback_on:
            raise GovernanceValidationError("error is not a configured fallback trigger")
        cost = 0.001
        result = {
            "selectedModelId": active.fallback_model_id,
            "trigger": error,
            "attempts": min(active.max_attempts, 2),
            "estimatedCostUsd": cost,
            "secretRef": active.secret_ref,
        }
        def operation(current: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            audit = self._audit(
                action="MODEL_FALLBACK_SIMULATED", actor=actor, target_type="MODEL",
                target_id=config_id, version_id=active.version_id,
                after={"trigger": error, "selectedModelId": active.fallback_model_id, "estimatedCostUsd": cost},
            )
            return replace_model(current, audits=(*current.audits, audit)), result
        return self._mutate(operation)

    def list_models(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["model"])
        state = self._ensured()
        return [
            {
                "config": item.model_dump(mode="json"),
                "active": _public_model(_find_model_version(state, item.active_version_id))
                if item.active_version_id
                else None,
            }
            for item in state.model_configs
        ]

    def create_flag_candidate(
        self,
        *,
        flag_id: str,
        value: str,
        environment: str,
        expires_at: datetime | None,
        reason: str,
        actor: ActorContext,
        percent: int | None = None,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["flag_write"])
        spec = FLAG_CATALOG.get(flag_id)
        if spec is None:
            raise GovernanceValidationError(f"unknown feature flag {flag_id}")
        if spec["safety_locked"] and value.lower() in {"false", "disabled"}:
            raise GovernanceValidationError("safety-critical flags cannot be disabled from the general UI")
        if environment == "prod" and expires_at is None:
            raise GovernanceValidationError("production flags require an expiry")

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            flag = next((item for item in state.flags if item.flag_id == flag_id), None)
            if flag is None:
                raise GovernanceNotFoundError(flag_id)
            now = self._clock()
            version = FlagVersion(
                version_id=str(uuid.uuid4()),
                flag_id=flag_id,
                status="CANDIDATE",
                value=value,
                environment=environment,
                percent=percent,
                effective_at=now,
                expires_at=expires_at,
                created_by=actor.user_id,
                created_at=now,
                change_reason=reason,
            )
            next_flag = replace_model(flag, etag=flag.etag + 1)
            audit = self._audit(
                action="FLAG_CANDIDATE_CREATED", actor=actor, target_type="FLAG",
                target_id=flag_id, version_id=version.version_id, reason=reason,
                after=version.model_dump(mode="json"),
            )
            result = {"flag": next_flag.model_dump(mode="json"), "version": version.model_dump(mode="json")}
            return replace_model(
                state,
                flags=_upsert(state.flags, next_flag, "flag_id"),
                flag_versions=(*state.flag_versions, version),
                audits=(*state.audits, audit),
            ), result

        return self._mutate(operation)

    def approve_flag(self, *, flag_id: str, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["flag_approve"])
        return self._mutate(lambda state: _approve_flag(state, flag_id, version_id, reason, actor, self._audit(
            action="FLAG_APPROVED", actor=actor, target_type="FLAG",
            target_id=flag_id, version_id=version_id, reason=reason,
        )))

    def activate_flag(self, *, flag_id: str, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["flag_activate"])
        return self._mutate(lambda state: _activate_flag(
            state, flag_id, version_id, reason, actor, self._clock(),
            self._audit(
                action="FLAG_ACTIVATED", actor=actor, target_type="FLAG",
                target_id=flag_id, version_id=version_id, reason=reason,
            ),
        ))

    def effective_flag(self, flag_id: str, *, actor: ActorContext, environment: str = "lab") -> dict[str, Any]:
        self._require(actor, READ["flag"])
        state = self._ensured()
        flag = next((item for item in state.flags if item.flag_id == flag_id), None)
        if flag is None:
            raise GovernanceNotFoundError(flag_id)
        value = flag.default_value
        version = None
        if flag.active_version_id:
            version = next(item for item in state.flag_versions if item.version_id == flag.active_version_id)
            expired = version.expires_at is not None and version.expires_at <= self._clock()
            if version.status == "ACTIVE" and version.environment == environment and not expired:
                value = version.value
            elif expired:
                value = flag.default_value
        return {
            "flagId": flag_id,
            "value": value,
            "defaultValue": flag.default_value,
            "safetyLocked": flag.safety_locked,
            "version": version.model_dump(mode="json") if version else None,
        }

    def list_flags(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["flag"])
        state = self._ensured()
        return [
            {
                "flag": item.model_dump(mode="json"),
                "effective": self.effective_flag(item.flag_id, actor=actor)["value"],
            }
            for item in state.flags
        ]

    def request_role_change(
        self,
        *,
        target_principal: str,
        target_role: str | None,
        add_capabilities: tuple[str, ...],
        remove_capabilities: tuple[str, ...],
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["role_request"])
        added = set(add_capabilities)
        owned = set(CAPABILITIES.get(actor.role, ()))
        if target_principal in {actor.user_id, actor.role} and added - owned:
            raise GovernanceAuthorizationError("operators cannot grant themselves higher privileges")

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            change = RoleMappingChange(
                change_id=str(uuid.uuid4()),
                target_principal=target_principal,
                target_role=target_role,
                add_capabilities=add_capabilities,
                remove_capabilities=remove_capabilities,
                status="REQUESTED",
                requested_by=actor.user_id,
                requested_at=self._clock(),
                reason=reason,
            )
            audit = self._audit(
                action="ROLE_MAPPING_REQUESTED", actor=actor, target_type="ROLE_MAPPING",
                target_id=change.change_id, reason=reason, after=change.model_dump(mode="json"),
            )
            result = {"change": change.model_dump(mode="json")}
            return replace_model(
                state, role_changes=(*state.role_changes, change), audits=(*state.audits, audit)
            ), result

        return self._mutate(operation)

    def approve_role_change(self, *, change_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["role_approve"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            change = next((item for item in state.role_changes if item.change_id == change_id), None)
            if change is None:
                raise GovernanceNotFoundError(change_id)
            if change.requested_by == actor.user_id:
                raise GovernanceAuthorizationError("requester cannot approve their own role mapping")
            if change.status != "REQUESTED":
                raise GovernanceTransitionError("role mapping is not awaiting approval")
            updated = replace_model(
                change, status="APPROVED", decided_by=actor.user_id, decided_at=self._clock(), reason=reason,
            )
            granted = dict(state.granted_capabilities)
            current = set(granted.get(change.target_principal, ()))
            current.update(change.add_capabilities)
            current.difference_update(change.remove_capabilities)
            granted[change.target_principal] = tuple(sorted(current))
            audit = self._audit(
                action="ROLE_MAPPING_APPROVED", actor=actor, target_type="ROLE_MAPPING",
                target_id=change_id, reason=reason, after=updated.model_dump(mode="json"),
            )
            return replace_model(
                state,
                role_changes=_upsert(state.role_changes, updated, "change_id"),
                granted_capabilities=granted,
                audits=(*state.audits, audit),
            ), {"change": updated.model_dump(mode="json")}

        return self._mutate(operation)

    def revoke_principal(self, *, principal: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["role_revoke"])
        if principal == actor.user_id:
            raise GovernanceAuthorizationError("operators cannot use revoke to alter their own standing")

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            if principal in state.revoked_principals:
                return state, {"revoked": True, "principal": principal}
            audit = self._audit(
                action="PRINCIPAL_REVOKED", actor=actor, target_type="ROLE_MAPPING",
                target_id=principal, reason=reason,
            )
            return replace_model(
                state,
                revoked_principals=(*state.revoked_principals, principal),
                audits=(*state.audits, audit),
            ), {"revoked": True, "principal": principal}

        return self._mutate(operation)

    def list_role_changes(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["role"])
        return [item.model_dump(mode="json") for item in self._ensured().role_changes]

    def list_retention_policies(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["retention"])
        return [item.model_dump(mode="json") for item in self._ensured().retention_policies]

    def list_masking_policies(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["retention"])
        return [item.model_dump(mode="json") for item in self._ensured().masking_policies]

    def create_masking_candidate(
        self,
        *,
        policy_version: str,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])
        reject_secrets_and_injection(policy_version, label="masking policy version")
        if not policy_version.strip():
            raise GovernanceValidationError("masking policy version is required")
        try:
            pack = resolve_masking_pack(policy_version.strip())
        except KeyError as exc:
            raise GovernanceValidationError(str(exc)) from exc

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = MaskingPolicyVersion(
                version_id=str(uuid.uuid4()),
                policy_version=pack.policy_version,
                status="CANDIDATE",
                rules_hash=pack.rules_hash,
                created_by=actor.user_id,
                created_at=self._clock(),
                change_reason=reason,
            )
            audit = self._audit(
                action="MASKING_CANDIDATE_CREATED",
                actor=actor,
                target_type="MASKING",
                target_id=version.policy_version,
                version_id=version.version_id,
                reason=reason,
                after={
                    **version.model_dump(mode="json"),
                    "rules": {
                        "maskEmail": pack.mask_email,
                        "maskPhone": pack.mask_phone,
                        "maskEmployeeId": pack.mask_employee_id,
                        "maskNationalId": pack.mask_national_id,
                        "maskCredentials": pack.mask_credentials,
                    },
                },
            )
            return replace_model(
                state,
                masking_policies=(*state.masking_policies, version),
                audits=(*state.audits, audit),
            ), {"policy": version.model_dump(mode="json")}

        return self._mutate(operation)

    def approve_masking(self, *, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = next(
                (item for item in state.masking_policies if item.version_id == version_id),
                None,
            )
            if version is None:
                raise GovernanceNotFoundError(version_id)
            if version.created_by == actor.user_id:
                raise GovernanceAuthorizationError(
                    "requester cannot approve their own masking policy"
                )
            if version.status != "CANDIDATE":
                raise GovernanceTransitionError("masking policy is not awaiting approval")
            updated = replace_model(
                version,
                status="APPROVED",
                approved_by=actor.user_id,
                change_reason=reason,
            )
            audit = self._audit(
                action="MASKING_APPROVED",
                actor=actor,
                target_type="MASKING",
                target_id=version.policy_version,
                version_id=version_id,
                reason=reason,
            )
            return replace_model(
                state,
                masking_policies=_upsert(state.masking_policies, updated, "version_id"),
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._mutate(operation)

    def activate_masking(self, *, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = next(
                (item for item in state.masking_policies if item.version_id == version_id),
                None,
            )
            if version is None:
                raise GovernanceNotFoundError(version_id)
            if version.status != "APPROVED":
                raise GovernanceTransitionError("activation requires an approved masking policy")
            retired = [
                replace_model(item, status="RETIRED")
                if item.status == "ACTIVE" and item.version_id != version_id
                else item
                for item in state.masking_policies
            ]
            updated = replace_model(
                version,
                status="ACTIVE",
                activated_by=actor.user_id,
                activated_at=self._clock(),
                change_reason=reason,
            )
            audit = self._audit(
                action="MASKING_ACTIVATED",
                actor=actor,
                target_type="MASKING",
                target_id=version.policy_version,
                version_id=version_id,
                reason=reason,
            )
            return replace_model(
                state,
                masking_policies=_upsert(tuple(retired), updated, "version_id"),
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._mutate(operation)

    def create_retention_candidate(
        self,
        *,
        policy_id: str,
        ttl_days: int,
        migration_plan: str,
        reason: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])
        if not migration_plan.strip():
            raise GovernanceValidationError("TTL changes require a migration plan")
        reject_secrets_and_injection(migration_plan, label="migration plan")

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = RetentionPolicyVersion(
                version_id=str(uuid.uuid4()),
                policy_id=policy_id,
                status="CANDIDATE",
                ttl_days=ttl_days,
                migration_plan=migration_plan,
                created_by=actor.user_id,
                created_at=self._clock(),
                change_reason=reason,
            )
            audit = self._audit(
                action="RETENTION_CANDIDATE_CREATED", actor=actor, target_type="RETENTION",
                target_id=policy_id, version_id=version.version_id, reason=reason,
                after=version.model_dump(mode="json"),
            )
            return replace_model(
                state,
                retention_policies=(*state.retention_policies, version),
                audits=(*state.audits, audit),
            ), {"policy": version.model_dump(mode="json")}

        return self._mutate(operation)

    def approve_retention(self, *, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = next((item for item in state.retention_policies if item.version_id == version_id), None)
            if version is None:
                raise GovernanceNotFoundError(version_id)
            if version.created_by == actor.user_id:
                raise GovernanceAuthorizationError("requester cannot approve their own retention policy")
            updated = replace_model(
                version, status="APPROVED", approved_by=actor.user_id, change_reason=reason,
            )
            audit = self._audit(
                action="RETENTION_APPROVED", actor=actor, target_type="RETENTION",
                target_id=version.policy_id, version_id=version_id, reason=reason,
            )
            return replace_model(
                state,
                retention_policies=_upsert(state.retention_policies, updated, "version_id"),
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._mutate(operation)

    def activate_retention(self, *, version_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["retention_write"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            version = next((item for item in state.retention_policies if item.version_id == version_id), None)
            if version is None:
                raise GovernanceNotFoundError(version_id)
            if version.status != "APPROVED":
                raise GovernanceTransitionError("activation requires an approved retention policy")
            retired = [
                replace_model(item, status="RETIRED")
                if item.policy_id == version.policy_id and item.status == "ACTIVE"
                else item
                for item in state.retention_policies
            ]
            updated = replace_model(
                version, status="ACTIVE", activated_by=actor.user_id, activated_at=self._clock(),
                change_reason=reason,
            )
            audit = self._audit(
                action="RETENTION_ACTIVATED", actor=actor, target_type="RETENTION",
                target_id=version.policy_id, version_id=version_id, reason=reason,
            )
            return replace_model(
                state,
                retention_policies=_upsert(tuple(retired), updated, "version_id"),
                audits=(*state.audits, audit),
            ), {"policy": updated.model_dump(mode="json")}

        return self._mutate(operation)

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
    guidance = "\n".join(
        f"- {route} {label}: {count} verified examples"
        for (route, label), count in sorted(counts.items())
    )
    template = f"{baseline}\n\nVerified dataset guidance ({dataset_version}):\n{guidance}\n"
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
    versions = state.flag_versions
    if retired is not None:
        versions = _upsert(versions, retired, "version_id")
    return replace_model(
        state,
        flags=_upsert(state.flags, next_flag, "flag_id"),
        flag_versions=_upsert(versions, updated, "version_id"),
        audits=(*state.audits, audit),
    ), {"flag": next_flag.model_dump(mode="json"), "version": updated.model_dump(mode="json")}
