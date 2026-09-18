"""Assemble EvalRun records from case layers and quality-gate decisions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from .constants import (
    METRIC_VERSION,
    MIN_FLOW_ACCURACY,
    QUALITY_GATE_VERSION,
    REQUIRED_QUALITY_CASE_IDS,
    RUNNER_VERSION,
    SAFETY_CRITICAL_ROUTES,
)
from .eval_case_ops import (
    build_case,
    dataset_similarity_cases,
    estimate_cost_usd,
    estimate_latency_ms,
)
from .eval_flow import PromptFlowHarness
from .eval_flow_ops import case_manifest_entries, harness_fixture_metadata, version_binding
from .helpers import content_hash, fingerprint
from .models import EvalCaseResult, EvalRun, PromptVersion, utc_now

__all__ = ["EvalRunBuildRequest", "build_eval_run"]


@dataclass(frozen=True)
class EvalRunBuildRequest:
    candidate: PromptVersion
    baseline: PromptVersion | None
    examples: list[dict[str, Any]]
    actor_id: str
    taxonomy_version: str
    knowledge_release_id: str | None
    harness: PromptFlowHarness
    release_eligible: bool
    static_cases: list[EvalCaseResult]
    dataset_cases: list[EvalCaseResult]
    similarity_cases: list[EvalCaseResult]
    similarity_accuracy: float
    similarity_f1: float
    probes: list[dict[str, Any]]
    flow_cases: list[EvalCaseResult]
    flow_accuracy: float
    flow_baseline_accuracy: float | None
    flow_complete: bool


def resolve_quality_gates(
    *,
    cases: list[EvalCaseResult],
    flow_cases: list[EvalCaseResult],
    dataset_cases: list[EvalCaseResult],
    accuracy: float,
    baseline_accuracy: float | None,
    cost: float,
    baseline_cost: float | None,
    similarity_f1: float,
    examples: list[dict[str, Any]],
    release_eligible: bool,
    execution_complete: bool,
) -> tuple[bool, bool, bool, bool]:
    critical_passed = all(item.passed for item in cases if item.critical)
    if not execution_complete:
        # Incomplete runs cannot claim a finished safety evaluation for publish.
        critical_passed = False

    required_flows_ok = all(
        item.passed for item in flow_cases if item.case_id == "quality-required-flows"
    )
    # Simulation / non-release harnesses do not emit the quality-required case.
    if release_eligible and execution_complete and not any(
        item.case_id == "quality-required-flows" for item in flow_cases
    ):
        required_flows_ok = False

    min_accuracy_ok = accuracy + 1e-9 >= MIN_FLOW_ACCURACY
    if not (release_eligible and execution_complete):
        min_accuracy_ok = False

    quality_passed = (
        execution_complete
        and release_eligible
        and critical_passed
        and required_flows_ok
        and min_accuracy_ok
    )
    # Relative checks may only fail quality; never grant a pass by themselves.
    if baseline_accuracy is not None and accuracy + 1e-9 < baseline_accuracy - 0.05:
        quality_passed = False
    if baseline_cost is not None and cost > baseline_cost * 2:
        quality_passed = False
    if any(not item.passed for item in dataset_cases):
        quality_passed = False
    if similarity_f1 < 0.5 and examples and not execution_complete:
        quality_passed = False
    return critical_passed, quality_passed, required_flows_ok, min_accuracy_ok


def build_reproducibility(
    *,
    harness: PromptFlowHarness,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    probes: list[dict[str, Any]],
    release_eligible: bool,
    execution_complete: bool,
    critical_passed: bool,
    quality_passed: bool,
    required_flows_ok: bool,
    min_accuracy_ok: bool,
    accuracy: float,
    baseline_accuracy: float | None,
) -> dict[str, Any]:
    case_entries = case_manifest_entries(probes)
    fixture_meta = harness_fixture_metadata(harness)
    return {
        "qualityGateVersion": QUALITY_GATE_VERSION,
        "minFlowAccuracy": MIN_FLOW_ACCURACY,
        "scoringPolicyVersion": METRIC_VERSION,
        "runnerVersion": RUNNER_VERSION,
        "requiredQualityCaseIds": sorted(REQUIRED_QUALITY_CASE_IDS),
        "safetyCriticalRoutes": sorted(SAFETY_CRITICAL_ROUTES),
        "flowHarness": harness.name,
        "releaseEligible": release_eligible,
        "executionComplete": execution_complete,
        "fixture": fixture_meta,
        "fixtureHash": content_hash(fingerprint(fixture_meta)),
        "candidate": version_binding(candidate),
        "baseline": version_binding(baseline),
        "cases": case_entries,
        "caseContentHash": content_hash(fingerprint({"cases": case_entries})),
        "gates": {
            "executionComplete": execution_complete,
            "criticalPassed": critical_passed,
            "qualityPassed": quality_passed,
            "requiredFlowsOk": required_flows_ok,
            "minAccuracyOk": min_accuracy_ok,
            "accuracy": accuracy,
            "baselineAccuracy": baseline_accuracy,
        },
    }


def build_manifest_fingerprint(
    *,
    candidate: PromptVersion,
    taxonomy_version: str,
    knowledge_release_id: str | None,
    harness: PromptFlowHarness,
    release_eligible: bool,
    execution_complete: bool,
    reproducibility: dict[str, Any],
) -> str:
    return fingerprint(
        {
            "dataset": candidate.dataset_version,
            "taxonomy": taxonomy_version,
            "knowledge": knowledge_release_id,
            "model": candidate.model_id,
            "promptContentHash": candidate.content_hash,
            "promptTemplateHash": content_hash(candidate.template),
            "runner": RUNNER_VERSION,
            "metric": METRIC_VERSION,
            "qualityGate": QUALITY_GATE_VERSION,
            "minFlowAccuracy": MIN_FLOW_ACCURACY,
            "evaluationLayers": ["static", "dataset", "real_flow", "simulation_flow"],
            "flowHarness": harness.name,
            "releaseEligible": release_eligible,
            "executionComplete": execution_complete,
            "fixtureHash": reproducibility["fixtureHash"],
            "candidate": reproducibility["candidate"],
            "baseline": reproducibility["baseline"],
            "caseContentHash": reproducibility["caseContentHash"],
            "cases": reproducibility["cases"],
        }
    )


def assemble_eval_run(
    *,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    examples: list[dict[str, Any]],
    actor_id: str,
    taxonomy_version: str,
    knowledge_release_id: str | None,
    cases: list[EvalCaseResult],
    status: str,
    critical_passed: bool,
    quality_passed: bool,
    accuracy: float,
    baseline_accuracy: float | None,
    cost: float,
    baseline_cost: float | None,
    reproducibility: dict[str, Any],
    manifest: str,
) -> EvalRun:
    now = utc_now()
    return EvalRun(
        run_id=str(uuid.uuid4()),
        status=status,  # type: ignore[arg-type]
        target_type="PROMPT",
        target_id=candidate.prompt_id,
        version_id=candidate.version_id,
        baseline_version_id=baseline.version_id if baseline else None,
        dataset_version=candidate.dataset_version or "",
        taxonomy_version=taxonomy_version,
        knowledge_release_id=knowledge_release_id,
        model_id=candidate.model_id,
        runner_version=RUNNER_VERSION,
        metric_version=METRIC_VERSION,
        manifest_hash=content_hash(manifest),
        critical_passed=critical_passed,
        quality_passed=quality_passed,
        case_results=tuple(cases),
        accuracy=accuracy,
        baseline_accuracy=baseline_accuracy,
        estimated_cost_usd=cost,
        baseline_cost_usd=baseline_cost,
        latency_ms=estimate_latency_ms(template=candidate.template, examples=examples),
        baseline_latency_ms=(
            estimate_latency_ms(template=baseline.template, examples=examples)
            if baseline
            else None
        ),
        created_by=actor_id,
        created_at=now,
        completed_at=now,
        quality_gate_version=QUALITY_GATE_VERSION,
        reproducibility=reproducibility,
    )


def resolve_run_metrics(
    *,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    examples: list[dict[str, Any]],
    harness: PromptFlowHarness,
    similarity_accuracy: float,
    flow_accuracy: float,
    flow_baseline_accuracy: float | None,
    flow_complete: bool,
) -> tuple[float, float | None, float, float | None, bool, str]:
    cost = estimate_cost_usd(template=candidate.template, examples=examples)
    baseline_cost = (
        estimate_cost_usd(template=baseline.template, examples=examples) if baseline else None
    )
    accuracy = flow_accuracy if (flow_complete or harness.available) else similarity_accuracy
    baseline_accuracy = flow_baseline_accuracy
    if baseline_accuracy is None and baseline is not None:
        _, baseline_accuracy, _, _ = dataset_similarity_cases(examples)
    # status = execution finished; critical_passed = safety; quality_passed = absolute floor.
    execution_complete = flow_complete
    status = "COMPLETED" if execution_complete else "INCOMPLETE"
    return cost, baseline_cost, accuracy, baseline_accuracy, execution_complete, status


def build_eval_run(request: EvalRunBuildRequest) -> EvalRun:
    cases = [
        *request.static_cases,
        *request.dataset_cases,
        *request.similarity_cases,
        *request.flow_cases,
        build_case(
            "cost-estimation-method",
            "metrics",
            True,
            "char_token_heuristic_v2",
            critical=False,
        ),
    ]
    cost, baseline_cost, accuracy, baseline_accuracy, execution_complete, status = (
        resolve_run_metrics(
            candidate=request.candidate,
            baseline=request.baseline,
            examples=request.examples,
            harness=request.harness,
            similarity_accuracy=request.similarity_accuracy,
            flow_accuracy=request.flow_accuracy,
            flow_baseline_accuracy=request.flow_baseline_accuracy,
            flow_complete=request.flow_complete,
        )
    )
    critical_passed, quality_passed, required_flows_ok, min_accuracy_ok = resolve_quality_gates(
        cases=cases,
        flow_cases=request.flow_cases,
        dataset_cases=request.dataset_cases,
        accuracy=accuracy,
        baseline_accuracy=baseline_accuracy,
        cost=cost,
        baseline_cost=baseline_cost,
        similarity_f1=request.similarity_f1,
        examples=request.examples,
        release_eligible=request.release_eligible,
        execution_complete=execution_complete,
    )
    reproducibility = build_reproducibility(
        harness=request.harness,
        candidate=request.candidate,
        baseline=request.baseline,
        probes=request.probes,
        release_eligible=request.release_eligible,
        execution_complete=execution_complete,
        critical_passed=critical_passed,
        quality_passed=quality_passed,
        required_flows_ok=required_flows_ok,
        min_accuracy_ok=min_accuracy_ok,
        accuracy=accuracy,
        baseline_accuracy=baseline_accuracy,
    )
    manifest = build_manifest_fingerprint(
        candidate=request.candidate,
        taxonomy_version=request.taxonomy_version,
        knowledge_release_id=request.knowledge_release_id,
        harness=request.harness,
        release_eligible=request.release_eligible,
        execution_complete=execution_complete,
        reproducibility=reproducibility,
    )
    return assemble_eval_run(
        candidate=request.candidate,
        baseline=request.baseline,
        examples=request.examples,
        actor_id=request.actor_id,
        taxonomy_version=request.taxonomy_version,
        knowledge_release_id=request.knowledge_release_id,
        cases=cases,
        status=status,
        critical_passed=critical_passed,
        quality_passed=quality_passed,
        accuracy=accuracy,
        baseline_accuracy=baseline_accuracy,
        cost=cost,
        baseline_cost=baseline_cost,
        reproducibility=reproducibility,
        manifest=manifest,
    )
