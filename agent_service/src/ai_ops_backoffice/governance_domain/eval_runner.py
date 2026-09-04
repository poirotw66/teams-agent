from __future__ import annotations

import re
import uuid
from collections import Counter
from typing import Any

from .constants import (
    INJECTION_SIGNATURES,
    MAX_PROMPT_LENGTH,
    METRIC_VERSION,
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


def _real_flow_cases(
    *,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    examples: list[dict[str, Any]],
    harness: PromptFlowHarness,
) -> tuple[list[EvalCaseResult], float, float | None, bool]:
    probes = multi_turn_probe_examples()
    for index, example in enumerate(examples):
        probes.append(
            {
                "case_id": f"dataset-{index}",
                "text": str(example.get("text") or ""),
                "expected_route": str(example.get("expected_route") or ""),
                "label": str(example.get("label") or ""),
                "history": example.get("history") or [],
            }
        )

    if not harness.available:
        incomplete = [
            _case(
                "real-flow-available",
                "real_flow",
                False,
                "model_unavailable: real flow incomplete",
                critical=True,
            )
        ]
        return incomplete, 0.0, None, False

    results: list[EvalCaseResult] = [
        _case(
            "real-flow-harness",
            "real_flow",
            True,
            f"harness={harness.name}",
            critical=False,
        )
    ]
    pairs: list[tuple[str, str]] = []
    baseline_pairs: list[tuple[str, str]] = []
    for probe in probes:
        text = str(probe.get("text") or "")
        expected = str(probe.get("expected_route") or "")
        history = probe.get("history") if isinstance(probe.get("history"), list) else []
        observation = harness.observe(
            template=candidate.template,
            text=text,
            history=history,  # type: ignore[arg-type]
        )
        ok = observation.route == expected
        if expected == "REFUSED":
            ok = observation.refused_injection and observation.route == "REFUSED"
        pairs.append((expected, observation.route))
        results.append(
            _case(
                f"real-flow-{probe.get('case_id')}",
                "real_flow",
                ok,
                (
                    f"expected={expected} predicted={observation.route} "
                    f"template_chars={observation.used_template_chars} {observation.detail}"
                ),
                critical=expected == "REFUSED",
            )
        )
        if baseline is not None:
            baseline_obs = harness.observe(
                template=baseline.template,
                text=text,
                history=history,  # type: ignore[arg-type]
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
    complete = all(item.passed for item in results if item.critical)
    return results, accuracy, baseline_accuracy, complete


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
    harness = resolve_default_flow_harness(flow_harness)
    static_cases = _static_cases(candidate.template)
    dataset_cases = _dataset_cases(examples)
    similarity_cases, similarity_accuracy, _, similarity_f1 = _dataset_similarity_cases(examples)
    flow_cases, flow_accuracy, flow_baseline_accuracy, flow_complete = _real_flow_cases(
        candidate=candidate,
        baseline=baseline,
        examples=examples,
        harness=harness,
    )
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
    accuracy = flow_accuracy if flow_complete else similarity_accuracy
    baseline_accuracy = flow_baseline_accuracy
    if baseline_accuracy is None and baseline is not None:
        _, baseline_accuracy, _, _ = _dataset_similarity_cases(examples)

    quality_passed = flow_complete
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

    now = utc_now()
    manifest = fingerprint(
        {
            "dataset": candidate.dataset_version,
            "taxonomy": taxonomy_version,
            "knowledge": knowledge_release_id,
            "model": candidate.model_id,
            "runner": RUNNER_VERSION,
            "metric": METRIC_VERSION,
            "evaluationLayers": ["static", "dataset", "real_flow"],
            "flowHarness": harness.name,
            "flowComplete": flow_complete,
            "examples": sorted(
                f"{route}:{label}:{count}"
                for (route, label), count in Counter(
                    (str(item.get("expected_route")), str(item.get("label"))) for item in examples
                ).items()
            ),
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
