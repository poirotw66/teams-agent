"""Real-flow / simulation harness probes for governance prompt evaluation."""

from __future__ import annotations

from typing import Any

from .constants import (
    MIN_FLOW_ACCURACY,
    REQUIRED_QUALITY_CASE_IDS,
    SAFETY_CRITICAL_ROUTES,
    is_allowlisted_model,
)
from .eval_case_ops import build_case
from .eval_flow import PromptFlowHarness, multi_turn_probe_examples
from .helpers import content_hash, fingerprint
from .models import EvalCaseResult, PromptVersion

__all__ = [
    "case_manifest_entries",
    "harness_fixture_metadata",
    "harness_observe",
    "probe_catalog",
    "real_flow_cases",
    "version_binding",
]


def probe_is_safety_critical(probe: dict[str, Any]) -> bool:
    return str(probe.get("expected_route") or "") in SAFETY_CRITICAL_ROUTES


def probe_is_quality_required(probe: dict[str, Any]) -> bool:
    case_id = str(probe.get("case_id") or "")
    return case_id in REQUIRED_QUALITY_CASE_IDS


def probe_catalog(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    probes = multi_turn_probe_examples()
    for index, example in enumerate(examples):
        probes.append(
            {
                "case_id": f"dataset-{index}",
                "text": str(example.get("text") or ""),
                "expected_route": str(example.get("expected_route") or ""),
                "label": str(example.get("label") or ""),
                "expected_behaviors": list(example.get("expected_behaviors") or []),
                "history": example.get("history") or [],
            }
        )
    return probes


def case_manifest_entries(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for probe in probes:
        history = probe.get("history") if isinstance(probe.get("history"), list) else []
        setup = probe.get("setup") if isinstance(probe.get("setup"), str) else None
        identity = {
            "text": probe.get("text"),
            "history": history,
            "expectedRoute": probe.get("expected_route"),
            "behaviors": list(probe.get("expected_behaviors") or []),
            "setup": setup,
            "label": probe.get("label"),
            "caseId": probe.get("case_id"),
        }
        entries.append(
            {
                "caseId": probe.get("case_id"),
                "text": probe.get("text"),
                "history": history,
                "setup": setup,
                "expectedRoute": probe.get("expected_route"),
                "label": probe.get("label"),
                "expectedBehaviors": list(probe.get("expected_behaviors") or []),
                "qualityRequired": probe_is_quality_required(probe),
                "safetyCritical": probe_is_safety_critical(probe),
                "contentHash": content_hash(fingerprint(identity)),
            }
        )
    return entries


def harness_fixture_metadata(harness: PromptFlowHarness) -> dict[str, Any]:
    reader = getattr(harness, "reproducibility_metadata", None)
    if callable(reader):
        payload = reader()
        if isinstance(payload, dict):
            return payload
    name = str(getattr(harness, "name", "unknown") or "unknown")
    return {
        "version": f"{name}-no-fixture-metadata",
        "layer": "flowRegression",
        "knowledgeQualityAcceptance": False,
    }


def version_binding(version: PromptVersion | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {
        "versionId": version.version_id,
        "promptId": version.prompt_id,
        "contentHash": version.content_hash,
        "templateHash": content_hash(version.template),
        "modelId": version.model_id,
        "datasetVersion": version.dataset_version,
        "taxonomyVersion": version.taxonomy_version,
        "knowledgeReleaseId": version.knowledge_release_id,
        "status": version.status,
    }


def observation_matches(probe: dict[str, Any], observation: Any) -> tuple[bool, str]:
    expected = str(probe.get("expected_route") or "")
    expected_behaviors = {
        str(item) for item in (probe.get("expected_behaviors") or []) if str(item)
    }
    route_ok = observation.route == expected
    if expected == "REFUSED":
        route_ok = observation.refused_injection and observation.route == "REFUSED"
    missing = sorted(expected_behaviors - set(observation.observed_behaviors))
    behavior_ok = not missing
    if expected_behaviors and expected == "GREETING":
        if "friendly_reply" in expected_behaviors and not (observation.reply_text or "").strip():
            behavior_ok = False
            missing = sorted(set(missing) | {"friendly_reply_text"})
    ok = route_ok and behavior_ok
    detail = (
        f"expected={expected} predicted={observation.route} "
        f"behaviors_missing={missing or []} "
        f"template_chars={observation.used_template_chars} {observation.detail}"
    )
    return ok, detail


async def harness_observe(
    harness: PromptFlowHarness,
    *,
    template: str,
    text: str,
    history: list[dict[str, str]] | None,
    model_id: str | None,
    setup: str | None = None,
) -> Any:
    import inspect

    def _call_kwargs(fn: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "template": template,
            "text": text,
            "history": history,
            "model_id": model_id,
        }
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return kwargs
        parameters = signature.parameters
        accepts_var_kw = any(
            item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()
        )
        if setup is not None and ("setup" in parameters or accepts_var_kw):
            kwargs["setup"] = setup
        return kwargs

    aobserve = getattr(harness, "aobserve", None)
    if callable(aobserve):
        return await aobserve(**_call_kwargs(aobserve))
    return harness.observe(**_call_kwargs(harness.observe))


def unavailable_flow_cases(harness: PromptFlowHarness) -> list[EvalCaseResult]:
    return [
        build_case(
            "real-flow-available",
            "real_flow",
            False,
            "model_unavailable: real flow incomplete",
            critical=True,
        ),
        build_case(
            "real-flow-release-eligible",
            "real_flow",
            False,
            f"harness={harness.name} release_eligible=False",
            critical=True,
        ),
    ]


def flow_gate_cases(
    *,
    harness: PromptFlowHarness,
    candidate: PromptVersion,
    release_eligible: bool,
    model_bound: bool,
) -> list[EvalCaseResult]:
    return [
        build_case(
            "real-flow-harness",
            "simulation_flow" if not release_eligible else "real_flow",
            True,
            (
                f"harness={harness.name} release_eligible={release_eligible} "
                f"model_id={candidate.model_id}"
            ),
            critical=False,
        ),
        build_case(
            "real-flow-release-eligible",
            "real_flow",
            release_eligible,
            (
                f"harness={harness.name} is simulation-only; not a publish gate"
                if not release_eligible
                else f"harness={harness.name} release_eligible"
            ),
            critical=True,
        ),
        build_case(
            "real-flow-model-bound",
            "real_flow",
            model_bound if release_eligible else True,
            (
                f"model_id={candidate.model_id} allowlisted={model_bound}"
                if release_eligible
                else "skipped_for_simulation_harness"
            ),
            critical=release_eligible,
        ),
    ]


async def run_flow_probes(
    *,
    probes: list[dict[str, Any]],
    harness: PromptFlowHarness,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    release_eligible: bool,
) -> tuple[list[EvalCaseResult], list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, bool]]]:
    results: list[EvalCaseResult] = []
    pairs: list[tuple[str, str]] = []
    baseline_pairs: list[tuple[str, str]] = []
    quality_probe_results: list[tuple[str, bool]] = []
    category = "simulation_flow" if not release_eligible else "real_flow"
    for probe in probes:
        text = str(probe.get("text") or "")
        expected = str(probe.get("expected_route") or "")
        history = probe.get("history") if isinstance(probe.get("history"), list) else []
        setup = probe.get("setup") if isinstance(probe.get("setup"), str) else None
        case_id = str(probe.get("case_id") or "")
        observation = await harness_observe(
            harness,
            template=candidate.template,
            text=text,
            history=history,  # type: ignore[arg-type]
            model_id=candidate.model_id,
            setup=setup,
        )
        ok, detail = observation_matches(probe, observation)
        pairs.append((expected, observation.route))
        results.append(
            build_case(
                f"{'sim' if not release_eligible else 'real'}-flow-{case_id}",
                category,
                ok,
                detail,
                critical=release_eligible and probe_is_safety_critical(probe),
            )
        )
        if release_eligible and probe_is_quality_required(probe):
            quality_probe_results.append((case_id, ok))
        if baseline is not None:
            baseline_obs = await harness_observe(
                harness,
                template=baseline.template,
                text=text,
                history=history,  # type: ignore[arg-type]
                model_id=baseline.model_id or candidate.model_id,
                setup=setup,
            )
            baseline_pairs.append((expected, baseline_obs.route))
    return results, pairs, baseline_pairs, quality_probe_results


def append_quality_gate_cases(
    results: list[EvalCaseResult],
    *,
    quality_probe_results: list[tuple[str, bool]],
    accuracy: float,
) -> None:
    missing_required = sorted(
        REQUIRED_QUALITY_CASE_IDS - {item[0] for item in quality_probe_results}
    )
    required_ok = (not missing_required) and all(passed for _, passed in quality_probe_results)
    results.append(
        build_case(
            "quality-required-flows",
            "quality_gate",
            required_ok,
            (
                f"required={sorted(REQUIRED_QUALITY_CASE_IDS)} "
                f"missing={missing_required} "
                f"failed={[case for case, passed in quality_probe_results if not passed]}"
            ),
            critical=False,
        )
    )
    results.append(
        build_case(
            "quality-min-accuracy",
            "quality_gate",
            accuracy + 1e-9 >= MIN_FLOW_ACCURACY,
            f"accuracy={accuracy:.4f} min={MIN_FLOW_ACCURACY}",
            critical=False,
        )
    )


async def real_flow_cases(
    *,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    examples: list[dict[str, Any]],
    harness: PromptFlowHarness,
) -> tuple[list[EvalCaseResult], float, float | None, bool]:
    probes = probe_catalog(examples)
    release_eligible = bool(getattr(harness, "release_eligible", False))

    if not harness.available:
        return unavailable_flow_cases(harness), 0.0, None, False

    model_bound = is_allowlisted_model(candidate.model_id)
    results = flow_gate_cases(
        harness=harness,
        candidate=candidate,
        release_eligible=release_eligible,
        model_bound=model_bound,
    )
    if release_eligible and not model_bound:
        return results, 0.0, None, False

    probe_cases, pairs, baseline_pairs, quality_probe_results = await run_flow_probes(
        probes=probes,
        harness=harness,
        candidate=candidate,
        baseline=baseline,
        release_eligible=release_eligible,
    )
    results.extend(probe_cases)

    accuracy = (
        sum(1 for expected, predicted in pairs if expected == predicted) / len(pairs)
        if pairs
        else 1.0
    )
    baseline_accuracy = None
    if baseline_pairs:
        baseline_accuracy = sum(
            1 for expected, predicted in baseline_pairs if expected == predicted
        ) / len(baseline_pairs)

    if release_eligible:
        append_quality_gate_cases(
            results,
            quality_probe_results=quality_probe_results,
            accuracy=accuracy,
        )

    # Execution complete = release-eligible harness finished all probes with a bound model.
    # Safety and quality gates are evaluated separately afterwards.
    complete = release_eligible and model_bound and bool(pairs)
    return results, accuracy, baseline_accuracy, complete
