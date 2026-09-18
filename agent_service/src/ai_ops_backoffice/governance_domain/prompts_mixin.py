from __future__ import annotations

import difflib
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
)
from .eval_runner import evaluate_prompt_async
from .helpers import (
    public_prompt,
    sticky_bucket,
)
from .models import (
    GovernanceState,
)
from .prompt_canary_ops import (
    evaluate_canary_thresholds,
    start_canary_operation,
    stop_canary_operation,
    validate_canary_percent,
)
from .prompt_candidate_ops import (
    commit_prompt_eval,
    create_candidate_operation,
    peek_runtime_selection,
    resolve_selected_prompt,
    rollback_prompt_operation,
)
from .service_helpers import (
    _activate_prompt,
    _active_prompt,
    _approve_prompt,
    _find_prompt,
    _find_prompt_version,
    _verified_examples,
)

Clock = Callable[[], datetime]


class GovernancePromptsMixin:
    def list_prompts(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        self._require(actor, READ["prompt"])
        state = self._ensured()
        include = actor.has_capability(READ["prompt_content"])
        return [
            {
                "prompt": item.model_dump(mode="json"),
                "active": public_prompt(
                    _active_prompt(state, item.prompt_id), include_content=include
                )
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

    def prompt_diff(
        self, prompt_id: str, version_id: str, *, actor: ActorContext
    ) -> dict[str, Any]:
        detail = self.prompt_detail(prompt_id, actor=actor)
        include = actor.has_capability(READ["prompt_content"])
        state = self._ensured()
        candidate = _find_prompt_version(state, version_id)
        baseline = _active_prompt(state, prompt_id)
        diff = None
        if include:
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
            "activeUnchanged": baseline.version_id
            == _find_prompt(state, prompt_id).active_version_id,
            "diff": diff,
            "eval": next(
                (
                    item.model_dump(mode="json")
                    for item in state.eval_runs
                    if item.run_id == candidate.eval_run_id
                ),
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

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            return create_candidate_operation(
                state,
                prompt_id=prompt_id,
                dataset_version=dataset_version,
                taxonomy_version=taxonomy_version,
                knowledge_release_id=knowledge_release_id,
                verified_examples=verified_examples,
                actor=actor,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                now=self._clock(),
                make_audit=self._audit,
            )

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
            return commit_prompt_eval(
                state,
                prompt_id=prompt_id,
                version_id=version_id,
                snapshot=version,
                run=run,
                actor=actor,
                make_audit=self._audit,
            )

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
                state,
                prompt_id=prompt_id,
                version_id=version_id,
                reason=reason,
                actor=actor,
                policy_exception_reason=policy_exception_reason,
                policy_exception_expires_at=policy_exception_expires_at,
                audit=self._audit(
                    action="PROMPT_APPROVED",
                    actor=actor,
                    target_type="PROMPT",
                    target_id=prompt_id,
                    version_id=version_id,
                    reason=reason,
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
        validate_canary_percent(percent)
        return self._mutate(
            lambda state: start_canary_operation(
                state,
                prompt_id=prompt_id,
                version_id=version_id,
                percent=percent,
                environment=environment,
                reason=reason,
                actor=actor,
                audit=self._audit(
                    action="PROMPT_CANARY_STARTED",
                    actor=actor,
                    target_type="PROMPT",
                    target_id=prompt_id,
                    version_id=version_id,
                    reason=reason,
                ),
            )
        )

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
                state,
                prompt_id=prompt_id,
                version_id=version_id,
                reason=reason,
                actor=actor,
                emergency=emergency,
                now=self._clock(),
                audit=self._audit(
                    action="PROMPT_ACTIVATED",
                    actor=actor,
                    target_type="PROMPT",
                    target_id=prompt_id,
                    version_id=version_id,
                    reason=reason,
                ),
            )
        )

    def rollback_prompt(
        self, *, prompt_id: str, reason: str, actor: ActorContext
    ) -> dict[str, Any]:
        self._require(actor, WRITE["prompt_rollback"])
        return self._mutate(
            lambda state: rollback_prompt_operation(
                state,
                prompt_id=prompt_id,
                reason=reason,
                actor=actor,
                now=self._clock(),
                make_audit=self._audit,
            )
        )

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
        _prompt, selected = resolve_selected_prompt(
            state, prompt_id, tenant=tenant, conversation_id=conversation_id
        )
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
        return peek_runtime_selection(
            state, prompt_id, tenant=tenant, conversation_id=conversation_id
        )

    def stop_prompt_canary(
        self,
        *,
        prompt_id: str,
        reason: str,
        actor: ActorContext,
        rollback: bool = False,
    ) -> dict[str, Any]:
        self._require(actor, WRITE["prompt_canary"])
        return self._mutate(
            lambda state: stop_canary_operation(
                state,
                prompt_id=prompt_id,
                reason=reason,
                actor=actor,
                rollback=rollback,
                now=self._clock(),
                make_audit=self._audit,
            )
        )

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
        decision = evaluate_canary_thresholds(
            prompt_id=prompt_id,
            error_rate=error_rate,
            negative_feedback_rate=negative_feedback_rate,
            handoff_rate=handoff_rate,
            safety_alerts=safety_alerts,
            sample_size=sample_size,
        )
        if decision["decision"] == "CONTINUE":
            return {
                "action": decision["action"],
                "reason": decision["reason"],
                "promptId": decision["promptId"],
            }
        stop_reason = (
            "critical safety alert during canary"
            if decision["reason"] == "critical safety alert"
            else "canary stop thresholds exceeded"
        )
        stopped = self.stop_prompt_canary(
            prompt_id=prompt_id,
            reason=stop_reason,
            actor=actor,
            rollback=False,
        )
        return {**stopped, "reason": decision["reason"]}
