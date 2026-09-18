"""Governance prompt/model evaluation runner facade.

Case builders, flow probes, and EvalRun assembly live in sibling modules;
this module owns the public evaluate_* entry points and stable private aliases.
"""

from __future__ import annotations

import uuid
from typing import Any

from .constants import METRIC_VERSION, RUNNER_VERSION, is_allowlisted_model
from .eval_case_ops import build_case, dataset_cases, dataset_similarity_cases, static_cases
from .eval_flow import PromptFlowHarness, resolve_default_flow_harness
from .eval_flow_ops import (
    case_manifest_entries,
    harness_observe,
    probe_catalog,
    real_flow_cases,
)
from .eval_run_ops import EvalRunBuildRequest, build_eval_run
from .helpers import content_hash
from .models import EvalRun, PromptVersion, utc_now

# Stable private aliases for tests that import underscore-prefixed helpers.
_case = build_case
_static_cases = static_cases
_dataset_cases = dataset_cases
_dataset_similarity_cases = dataset_similarity_cases
_case_manifest_entries = case_manifest_entries
_harness_observe = harness_observe
_probe_catalog = probe_catalog
_real_flow_cases = real_flow_cases
_build_eval_run = build_eval_run

__all__ = [
    "evaluate_model",
    "evaluate_prompt",
    "evaluate_prompt_async",
]


async def evaluate_prompt_async(
    *,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    examples: list[dict[str, Any]],
    actor_id: str,
    taxonomy_version: str,
    knowledge_release_id: str | None,
    flow_harness: PromptFlowHarness | None = None,
) -> EvalRun:
    harness = resolve_default_flow_harness(flow_harness)
    release_eligible = bool(getattr(harness, "release_eligible", False))
    static = static_cases(candidate.template)
    dataset = dataset_cases(examples)
    similarity_cases, similarity_accuracy, _, similarity_f1 = dataset_similarity_cases(examples)
    probes = probe_catalog(examples)
    flow_cases, flow_accuracy, flow_baseline_accuracy, flow_complete = await real_flow_cases(
        candidate=candidate,
        baseline=baseline,
        examples=examples,
        harness=harness,
    )
    return build_eval_run(
        EvalRunBuildRequest(
            candidate=candidate,
            baseline=baseline,
            examples=examples,
            actor_id=actor_id,
            taxonomy_version=taxonomy_version,
            knowledge_release_id=knowledge_release_id,
            harness=harness,
            release_eligible=release_eligible,
            static_cases=static,
            dataset_cases=dataset,
            similarity_cases=similarity_cases,
            similarity_accuracy=similarity_accuracy,
            similarity_f1=similarity_f1,
            probes=probes,
            flow_cases=flow_cases,
            flow_accuracy=flow_accuracy,
            flow_baseline_accuracy=flow_baseline_accuracy,
            flow_complete=flow_complete,
        )
    )


def evaluate_prompt(
    *,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    examples: list[dict[str, Any]],
    actor_id: str,
    taxonomy_version: str,
    knowledge_release_id: str | None,
    flow_harness: PromptFlowHarness | None = None,
) -> EvalRun:
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            evaluate_prompt_async(
                candidate=candidate,
                baseline=baseline,
                examples=examples,
                actor_id=actor_id,
                taxonomy_version=taxonomy_version,
                knowledge_release_id=knowledge_release_id,
                flow_harness=flow_harness,
            )
        )
    raise RuntimeError(
        "evaluate_prompt() cannot run inside an event loop; "
        "await evaluate_prompt_async() instead"
    )


def evaluate_model(*, version: Any, actor_id: str) -> EvalRun:
    from .constants import FALLBACK_TRIGGERS

    allowed = is_allowlisted_model(version.model_id, provider=version.provider)
    fallback_ok = not version.fallback_on or set(version.fallback_on) <= FALLBACK_TRIGGERS
    cases = [
        build_case(
            "allowlist",
            "model_allowlist",
            allowed,
            f"{version.provider}/{version.model_id}",
            critical=True,
        ),
        build_case(
            "secret-ref",
            "secret",
            version.secret_ref.startswith("secret://"),
            version.secret_ref,
            critical=True,
        ),
        build_case(
            "fallback",
            "fallback",
            fallback_ok,
            ",".join(version.fallback_on),
            critical=True,
        ),
    ]
    now = utc_now()
    return EvalRun(
        run_id=str(uuid.uuid4()),
        status="COMPLETED",
        target_type="MODEL",
        target_id=version.config_id,
        version_id=version.version_id,
        baseline_version_id=None,
        dataset_version="model-static",
        taxonomy_version="n/a",
        knowledge_release_id=None,
        model_id=version.model_id,
        runner_version=RUNNER_VERSION,
        metric_version=METRIC_VERSION,
        manifest_hash=content_hash(version.content_hash),
        critical_passed=all(item.passed for item in cases),
        quality_passed=True,
        case_results=tuple(cases),
        accuracy=1.0 if allowed else 0.0,
        estimated_cost_usd=0.0,
        latency_ms=0.0,
        created_by=actor_id,
        created_at=now,
        completed_at=now,
    )
