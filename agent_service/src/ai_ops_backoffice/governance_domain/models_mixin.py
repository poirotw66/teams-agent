from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from operations_core.access import ActorContext

from .constants import (
    READ,
    WRITE,
)
from .errors import (
    GovernanceNotFoundError,
    GovernanceTransitionError,
    GovernanceValidationError,
)
from .eval_runner import evaluate_model
from .helpers import (
    content_hash,
    require_secret_ref,
)
from .model_catalog import assert_component_models, component_effect
from .model_schedule import (
    complete_model_schedule,
    fail_model_schedule,
    mark_model_schedule_running,
    schedule_model_version,
)
from .models import (
    GovernanceState,
    ModelConfigRecord,
    ModelConfigVersion,
    replace_model,
)

Clock = Callable[[], datetime]




from .service_helpers import (
    _activate_model,
    _approve_model,
    _find_model,
    _find_model_version,
    _public_model,
    _upsert,
    _validate_model,
)


class GovernanceModelsMixin:
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
            "temperature": version.temperature,
            "maxOutputTokens": version.max_output_tokens,
            "timeoutSeconds": version.timeout_seconds,
            "retry": version.retry,
            "maxAttempts": version.max_attempts,
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
        assert_component_models(
            config_id=config_id,
            component=component,
            provider=provider,
            model_id=model_id,
            fallback_model_id=fallback_model_id,
        )
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
                before={"status": version.status},
                after={"status": "EVALUATED", "criticalPassed": run.critical_passed},
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
        if component_effect(config_id) != "next_request":
            raise GovernanceTransitionError(
                "this component must be scheduled; activation does not switch it immediately"
            )
        return self._mutate(lambda state: _activate_model(
            state, config_id, version_id, reason, actor, self._clock(),
            self._audit(
                action="MODEL_ACTIVATED", actor=actor, target_type="MODEL",
                target_id=config_id, version_id=version_id, reason=reason,
            ),
        ))

    def schedule_model(
        self, *, config_id: str, version_id: str, reason: str, actor: ActorContext
    ) -> dict[str, Any]:
        self._require(actor, WRITE["model_activate"])
        return self._mutate(lambda state: schedule_model_version(
            state,
            config_id=config_id,
            version_id=version_id,
            reason=reason,
            actor=actor,
            now=self._clock(),
            audit=self._audit(
                action="MODEL_SCHEDULED",
                actor=actor,
                target_type="MODEL",
                target_id=config_id,
                version_id=version_id,
                reason=reason,
            ),
        ))

    def mark_schedule_running(
        self, *, config_id: str, version_id: str, actor: ActorContext
    ) -> dict[str, Any]:
        self._require(actor, WRITE["model_activate"])
        return self._mutate(lambda state: mark_model_schedule_running(
            state,
            config_id=config_id,
            version_id=version_id,
            audit=self._audit(
                action="MODEL_SCHEDULE_RUNNING",
                actor=actor,
                target_type="MODEL",
                target_id=config_id,
                version_id=version_id,
            ),
        ))

    def complete_schedule(
        self, *, config_id: str, version_id: str, actor: ActorContext, reason: str
    ) -> dict[str, Any]:
        self._require(actor, WRITE["model_activate"])
        return self._mutate(lambda state: complete_model_schedule(
            state,
            config_id=config_id,
            version_id=version_id,
            actor=actor,
            now=self._clock(),
            audit=self._audit(
                action="MODEL_SCHEDULE_APPLIED",
                actor=actor,
                target_type="MODEL",
                target_id=config_id,
                version_id=version_id,
                reason=reason,
            ),
        ))

    def fail_schedule(
        self, *, config_id: str, version_id: str, reason: str, actor: ActorContext
    ) -> dict[str, Any]:
        self._require(actor, WRITE["model_activate"])
        return self._mutate(lambda state: fail_model_schedule(
            state,
            config_id=config_id,
            version_id=version_id,
            reason=reason,
            audit=self._audit(
                action="MODEL_SCHEDULE_FAILED",
                actor=actor,
                target_type="MODEL",
                target_id=config_id,
                version_id=version_id,
                reason=reason,
            ),
        ))

    def rollback_model(self, *, config_id: str, reason: str, actor: ActorContext) -> dict[str, Any]:
        self._require(actor, WRITE["model_activate"])

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            config = _find_model(state, config_id)
            if not config.previous_healthy_version_id:
                raise GovernanceTransitionError("no healthy model version is available to rollback")
            if component_effect(config_id) != "next_request":
                return schedule_model_version(
                    state,
                    config_id=config_id,
                    version_id=config.previous_healthy_version_id,
                    reason=reason,
                    actor=actor,
                    now=self._clock(),
                    allow_retired=True,
                    audit=self._audit(
                        action="MODEL_ROLLBACK_SCHEDULED",
                        actor=actor,
                        target_type="MODEL",
                        target_id=config_id,
                        version_id=config.previous_healthy_version_id,
                        reason=reason,
                    ),
                )
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
                before={"activeVersionId": current.version_id},
                after={"activeVersionId": previous.version_id},
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

    def peek_model_schedule(self, config_id: str) -> dict[str, Any] | None:
        """Read-only schedule pointer. Does not change the active version."""
        state = self._repository.load()
        config = next((item for item in state.model_configs if item.config_id == config_id), None)
        if config is None or not config.scheduled_version_id:
            return None
        version = _find_model_version(state, config.scheduled_version_id)
        return {
            "scheduledVersionId": config.scheduled_version_id,
            "scheduleKind": config.schedule_kind,
            "scheduleStatus": config.schedule_status,
            "scheduledModelId": version.model_id,
            "provider": version.provider,
        }

    def list_models(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["model"])
        state = self._ensured()
        return [
            {
                "config": item.model_dump(mode="json"),
                "active": _public_model(_find_model_version(state, item.active_version_id))
                if item.active_version_id
                else None,
                "schedule": {
                    "scheduledVersionId": item.scheduled_version_id,
                    "scheduleKind": item.schedule_kind,
                    "scheduleStatus": item.schedule_status,
                    "scheduledModelId": (
                        _find_model_version(state, item.scheduled_version_id).model_id
                        if item.scheduled_version_id
                        else None
                    ),
                },
                "versions": [
                    _public_model(v)
                    for v in state.model_versions
                    if v.config_id == item.config_id
                ],
            }
            for item in state.model_configs
        ]
