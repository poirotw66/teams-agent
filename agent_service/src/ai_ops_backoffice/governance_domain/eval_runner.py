from __future__ import annotations

import re
import uuid
from collections import Counter
from typing import Any

from .constants import (
    INJECTION_SIGNATURES,
    MAX_PROMPT_LENGTH,
    METRIC_VERSION,
    PROVIDER_MODELS,
    RUNNER_VERSION,
)
from .eval_flow import (
    PromptFlowHarness,
    multi_turn_probe_examples,
    resolve_default_flow_harness,
)
from .helpers import content_hash, fingerprint
from .models import EvalCaseResult, EvalRun, PromptVersion, utc_now

SCHEMA_TOKENS = ("{max_issues}", "{faq_keys}")
CREDENTIAL_SOLICIT = re.compile(r"(?i)(ask|request|require).{0,40}(password|api key|otp|token)")
TOKEN_CHARS = 4
INPUT_COST_PER_1K = 0.00015
OUTPUT_COST_PER_1K = 0.0006
MIN_VERIFIED_EXAMPLES = 3
_ALLOWED_MODELS = frozenset(
    model_id for models in PROVIDER_MODELS.values() for model_id in models
)


def _case(case_id: str, category: str, passed: bool, detail: str, *, critical: bool) -> EvalCaseResult:
    return EvalCaseResult(
        case_id=case_id,
        category=category,
        critical=critical,
        passed=passed,
        detail=detail,
    )


def _static_cases(template: str) -> list[EvalCaseResult]:
    missing = [token for token in SCHEMA_TOKENS if token not in template]
    lowered = template.casefold()
    injection = any(signature in lowered for signature in INJECTION_SIGNATURES)
    credential = _solicits_credentials(template)
    return [
        _case(
            "schema-tokens",
            "static",
            not missing,
            "missing " + ", ".join(missing) if missing else "schema tokens present",
            critical=True,
        ),
        _case(
            "prompt-length",
            "static",
            len(template) <= MAX_PROMPT_LENGTH,
            f"length={len(template)}",
            critical=True,
        ),
        _case(
            "prompt-injection-signature",
            "static",
            not injection,
            "injection signature present" if injection else "no injection signature",
            critical=True,
        ),
        _case(
            "credential-solicit",
            "static",
            not credential,
            "template solicits credentials" if credential else "no credential solicitation",
            critical=True,
        ),
    ]


def _solicits_credentials(template: str) -> bool:
    for match in CREDENTIAL_SOLICIT.finditer(template):
        window = template[max(0, match.start() - 24) : match.start()].casefold()
        if any(token in window for token in ("never", "do not", "don't", "must not", "禁止", "不得")):
            continue
        return True
    return False


def _dataset_cases(examples: list[dict[str, Any]]) -> list[EvalCaseResult]:
    texts = [str(item.get("text") or "").strip() for item in examples]
    routes = [str(item.get("expected_route") or "") for item in examples]
    nonempty = [text for text in texts if text]
    unique_texts = {text.casefold() for text in nonempty}
    route_counts = Counter(routes)
    return [
        _case(
            "dataset-size",
            "dataset",
            len(nonempty) >= MIN_VERIFIED_EXAMPLES,
            f"verified_examples={len(nonempty)} min={MIN_VERIFIED_EXAMPLES}",
            critical=False,
        ),
        _case(
            "dataset-duplicates",
            "dataset",
            len(unique_texts) == len(nonempty),
            f"unique={len(unique_texts)} total={len(nonempty)}",
            critical=False,
        ),
        _case(
            "dataset-route-coverage",
            "dataset",
            len(route_counts) >= 2 or len(nonempty) < MIN_VERIFIED_EXAMPLES,
            f"routes={dict(route_counts)}",
            critical=False,
        ),
    ]


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w\u3400-\u9fff]+", text.casefold()) if len(token) >= 2}


def _predict_route_label(
    text: str,
    training: list[dict[str, Any]],
) -> tuple[str, str]:
    query = _tokenize(text)
    best_score = -1.0
    best_route = "UNKNOWN"
    best_label = "UNKNOWN"
    for item in training:
        tokens = _tokenize(str(item.get("text") or ""))
        if not tokens:
            continue
        score = len(query & tokens) / max(1, len(query | tokens))
        if score > best_score:
            best_score = score
            best_route = str(item.get("expected_route") or "UNKNOWN")
            best_label = str(item.get("label") or "UNKNOWN")
    return best_route, best_label


def _macro_f1(pairs: list[tuple[str, str]]) -> float:
    labels = sorted({expected for expected, _ in pairs} | {predicted for _, predicted in pairs})
    if not labels:
        return 1.0
    scores: list[float] = []
    for label in labels:
        tp = sum(1 for expected, predicted in pairs if expected == label and predicted == label)
        fp = sum(1 for expected, predicted in pairs if expected != label and predicted == label)
        fn = sum(1 for expected, predicted in pairs if expected == label and predicted != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        if precision + recall == 0:
            scores.append(0.0)
        else:
            scores.append(2 * precision * recall / (precision + recall))
    return sum(scores) / len(scores)


def _dataset_similarity_cases(
    examples: list[dict[str, Any]],
) -> tuple[list[EvalCaseResult], float, float, float]:
    """Dataset-only similarity probe — not proof that a prompt/model improved."""
    results: list[EvalCaseResult] = []
    route_pairs: list[tuple[str, str]] = []
    label_pairs: list[tuple[str, str]] = []
    for index, example in enumerate(examples):
        expected_route = str(example.get("expected_route") or "")
        expected_label = str(example.get("label") or "")
        text = str(example.get("text") or "")
        training = [item for offset, item in enumerate(examples) if offset != index] or [example]
        predicted_route, predicted_label = _predict_route_label(text, training)
        route_pairs.append((expected_route, predicted_route))
        label_pairs.append((expected_label, predicted_label))
        results.append(
            _case(
                f"dataset-sim-route-{index}",
                "dataset_similarity",
                predicted_route == expected_route,
                f"expected={expected_route} predicted={predicted_route}",
                critical=False,
            )
        )
    route_accuracy = (
        sum(1 for expected, predicted in route_pairs if expected == predicted) / len(route_pairs)
        if route_pairs
        else 1.0
    )
    label_accuracy = (
        sum(1 for expected, predicted in label_pairs if expected == predicted) / len(label_pairs)
        if label_pairs
        else 1.0
    )
    accuracy = (route_accuracy + label_accuracy) / 2
    return results, accuracy, route_accuracy, _macro_f1(route_pairs)


def _estimate_cost_usd(*, template: str, examples: list[dict[str, Any]]) -> float:
    system_tokens = max(1, len(template) // TOKEN_CHARS)
    output_tokens = 128
    total_input = 0
    total_output = 0
    for example in examples or [{"text": ""}]:
        user_tokens = max(1, len(str(example.get("text") or "")) // TOKEN_CHARS)
        total_input += system_tokens + user_tokens
        total_output += output_tokens
    return round(
        total_input / 1000 * INPUT_COST_PER_1K + total_output / 1000 * OUTPUT_COST_PER_1K,
        8,
    )


def _estimate_latency_ms(*, template: str, examples: list[dict[str, Any]]) -> float:
    per_example = 40 + len(template) // 120
    return float(max(20, per_example * max(1, len(examples))))


def _probe_catalog(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _case_manifest_entries(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for probe in probes:
        history = probe.get("history") if isinstance(probe.get("history"), list) else []
        entries.append(
            {
                "caseId": probe.get("case_id"),
                "text": probe.get("text"),
                "history": history,
                "expectedRoute": probe.get("expected_route"),
                "label": probe.get("label"),
                "expectedBehaviors": list(probe.get("expected_behaviors") or []),
                "contentHash": content_hash(
                    fingerprint(
                        {
                            "text": probe.get("text"),
                            "history": history,
                            "expectedRoute": probe.get("expected_route"),
                            "behaviors": list(probe.get("expected_behaviors") or []),
                        }
                    )
                ),
            }
        )
    return entries


def _observation_matches(probe: dict[str, Any], observation: Any) -> tuple[bool, str]:
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


async def _harness_observe(
    harness: PromptFlowHarness,
    *,
    template: str,
    text: str,
    history: list[dict[str, str]] | None,
    model_id: str | None,
    setup: str | None = None,
) -> Any:
    aobserve = getattr(harness, "aobserve", None)
    if callable(aobserve):
        try:
            return await aobserve(
                template=template,
                text=text,
                history=history,
                model_id=model_id,
                setup=setup,
            )
        except TypeError:
            return await aobserve(
                template=template, text=text, history=history, model_id=model_id
            )
    try:
        return harness.observe(
            template=template,
            text=text,
            history=history,
            model_id=model_id,
            setup=setup,
        )
    except TypeError:
        return harness.observe(
            template=template, text=text, history=history, model_id=model_id
        )


async def _real_flow_cases(
    *,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    examples: list[dict[str, Any]],
    harness: PromptFlowHarness,
) -> tuple[list[EvalCaseResult], float, float | None, bool]:
    probes = _probe_catalog(examples)
    release_eligible = bool(getattr(harness, "release_eligible", False))

    if not harness.available:
        incomplete = [
            _case(
                "real-flow-available",
                "real_flow",
                False,
                "model_unavailable: real flow incomplete",
                critical=True,
            ),
            _case(
                "real-flow-release-eligible",
                "real_flow",
                False,
                f"harness={harness.name} release_eligible=False",
                critical=True,
            ),
        ]
        return incomplete, 0.0, None, False

    model_bound = bool(candidate.model_id) and candidate.model_id in _ALLOWED_MODELS
    results: list[EvalCaseResult] = [
        _case(
            "real-flow-harness",
            "simulation_flow" if not release_eligible else "real_flow",
            True,
            (
                f"harness={harness.name} release_eligible={release_eligible} "
                f"model_id={candidate.model_id}"
            ),
            critical=False,
        ),
        _case(
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
        _case(
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
    if release_eligible and not model_bound:
        return results, 0.0, None, False

    pairs: list[tuple[str, str]] = []
    baseline_pairs: list[tuple[str, str]] = []
    category = "simulation_flow" if not release_eligible else "real_flow"
    for probe in probes:
        text = str(probe.get("text") or "")
        expected = str(probe.get("expected_route") or "")
        history = probe.get("history") if isinstance(probe.get("history"), list) else []
        setup = probe.get("setup") if isinstance(probe.get("setup"), str) else None
        observation = await _harness_observe(
            harness,
            template=candidate.template,
            text=text,
            history=history,  # type: ignore[arg-type]
            model_id=candidate.model_id,
            setup=setup,
        )
        ok, detail = _observation_matches(probe, observation)
        pairs.append((expected, observation.route))
        results.append(
            _case(
                f"{'sim' if not release_eligible else 'real'}-flow-{probe.get('case_id')}",
                category,
                ok,
                detail,
                critical=release_eligible and expected in {"REFUSED", "GREETING"},
            )
        )
        if baseline is not None:
            baseline_obs = await _harness_observe(
                harness,
                template=baseline.template,
                text=text,
                history=history,  # type: ignore[arg-type]
                model_id=baseline.model_id or candidate.model_id,
                setup=setup,
            )
            baseline_pairs.append((expected, baseline_obs.route))

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
    complete = release_eligible and all(
        item.passed for item in results if item.critical and item.category == "real_flow"
    )
    return results, accuracy, baseline_accuracy, complete


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
    static_cases = _static_cases(candidate.template)
    dataset_cases = _dataset_cases(examples)
    similarity_cases, similarity_accuracy, _, similarity_f1 = _dataset_similarity_cases(examples)
    probes = _probe_catalog(examples)
    flow_cases, flow_accuracy, flow_baseline_accuracy, flow_complete = await _real_flow_cases(
        candidate=candidate,
        baseline=baseline,
        examples=examples,
        harness=harness,
    )
    return _build_eval_run(
        candidate=candidate,
        baseline=baseline,
        examples=examples,
        actor_id=actor_id,
        taxonomy_version=taxonomy_version,
        knowledge_release_id=knowledge_release_id,
        harness=harness,
        release_eligible=release_eligible,
        static_cases=static_cases,
        dataset_cases=dataset_cases,
        similarity_cases=similarity_cases,
        similarity_accuracy=similarity_accuracy,
        similarity_f1=similarity_f1,
        probes=probes,
        flow_cases=flow_cases,
        flow_accuracy=flow_accuracy,
        flow_baseline_accuracy=flow_baseline_accuracy,
        flow_complete=flow_complete,
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


def _build_eval_run(
    *,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    examples: list[dict[str, Any]],
    actor_id: str,
    taxonomy_version: str,
    knowledge_release_id: str | None,
    harness: PromptFlowHarness,
    release_eligible: bool,
    static_cases: list[EvalCaseResult],
    dataset_cases: list[EvalCaseResult],
    similarity_cases: list[EvalCaseResult],
    similarity_accuracy: float,
    similarity_f1: float,
    probes: list[dict[str, Any]],
    flow_cases: list[EvalCaseResult],
    flow_accuracy: float,
    flow_baseline_accuracy: float | None,
    flow_complete: bool,
) -> EvalRun:
    cases = [
        *static_cases,
        *dataset_cases,
        *similarity_cases,
        *flow_cases,
        _case(
            "cost-estimation-method",
            "metrics",
            True,
            "char_token_heuristic_v2",
            critical=False,
        ),
    ]
    cost = _estimate_cost_usd(template=candidate.template, examples=examples)
    baseline_cost = (
        _estimate_cost_usd(template=baseline.template, examples=examples) if baseline else None
    )
    accuracy = flow_accuracy if (flow_complete or harness.available) else similarity_accuracy
    baseline_accuracy = flow_baseline_accuracy
    if baseline_accuracy is None and baseline is not None:
        _, baseline_accuracy, _, _ = _dataset_similarity_cases(examples)

    quality_passed = flow_complete and release_eligible
    if baseline_accuracy is not None and accuracy + 1e-9 < baseline_accuracy - 0.05:
        quality_passed = False
    if baseline_cost is not None and cost > baseline_cost * 2:
        quality_passed = False
    if any(not item.passed for item in dataset_cases):
        quality_passed = False
    if similarity_f1 < 0.5 and examples and not flow_complete:
        quality_passed = False

    critical_passed = all(item.passed for item in cases if item.critical)
    status = "COMPLETED" if flow_complete else "INCOMPLETE"
    if not flow_complete:
        critical_passed = False

    case_entries = _case_manifest_entries(probes)
    now = utc_now()
    manifest = fingerprint(
        {
            "dataset": candidate.dataset_version,
            "taxonomy": taxonomy_version,
            "knowledge": knowledge_release_id,
            "model": candidate.model_id,
            "promptContentHash": candidate.content_hash,
            "promptTemplateHash": content_hash(candidate.template),
            "runner": RUNNER_VERSION,
            "metric": METRIC_VERSION,
            "evaluationLayers": ["static", "dataset", "real_flow", "simulation_flow"],
            "flowHarness": harness.name,
            "releaseEligible": release_eligible,
            "flowComplete": flow_complete,
            "caseContentHash": content_hash(fingerprint({"cases": case_entries})),
            "cases": case_entries,
        }
    )
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
        latency_ms=_estimate_latency_ms(template=candidate.template, examples=examples),
        baseline_latency_ms=(
            _estimate_latency_ms(template=baseline.template, examples=examples)
            if baseline
            else None
        ),
        created_by=actor_id,
        created_at=now,
        completed_at=now,
    )


def evaluate_model(*, version: Any, actor_id: str) -> EvalRun:
    from .constants import FALLBACK_TRIGGERS, PROVIDER_MODELS

    allowed = version.model_id in PROVIDER_MODELS.get(version.provider, frozenset())
    fallback_ok = not version.fallback_on or set(version.fallback_on) <= FALLBACK_TRIGGERS
    cases = [
        _case("allowlist", "model_allowlist", allowed, f"{version.provider}/{version.model_id}", critical=True),
        _case("secret-ref", "secret", version.secret_ref.startswith("secret://"), version.secret_ref, critical=True),
        _case("fallback", "fallback", fallback_ok, ",".join(version.fallback_on), critical=True),
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
