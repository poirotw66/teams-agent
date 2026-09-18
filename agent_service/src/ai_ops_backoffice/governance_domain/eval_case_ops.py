"""Static and dataset case builders for governance prompt evaluation."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .constants import INJECTION_SIGNATURES, MAX_PROMPT_LENGTH
from .models import EvalCaseResult

__all__ = [
    "SCHEMA_TOKENS",
    "build_case",
    "dataset_cases",
    "dataset_similarity_cases",
    "estimate_cost_usd",
    "estimate_latency_ms",
    "static_cases",
]

SCHEMA_TOKENS = ("{max_issues}", "{faq_keys}")
CREDENTIAL_SOLICIT = re.compile(r"(?i)(ask|request|require).{0,40}(password|api key|otp|token)")
TOKEN_CHARS = 4
INPUT_COST_PER_1K = 0.00015
OUTPUT_COST_PER_1K = 0.0006
MIN_VERIFIED_EXAMPLES = 3


def build_case(
    case_id: str, category: str, passed: bool, detail: str, *, critical: bool
) -> EvalCaseResult:
    return EvalCaseResult(
        case_id=case_id,
        category=category,
        critical=critical,
        passed=passed,
        detail=detail,
    )


def solicits_credentials(template: str) -> bool:
    for match in CREDENTIAL_SOLICIT.finditer(template):
        window = template[max(0, match.start() - 24) : match.start()].casefold()
        if any(token in window for token in ("never", "do not", "don't", "must not", "禁止", "不得")):
            continue
        return True
    return False


def static_cases(template: str) -> list[EvalCaseResult]:
    missing = [token for token in SCHEMA_TOKENS if token not in template]
    lowered = template.casefold()
    injection = any(signature in lowered for signature in INJECTION_SIGNATURES)
    credential = solicits_credentials(template)
    return [
        build_case(
            "schema-tokens",
            "static",
            not missing,
            "missing " + ", ".join(missing) if missing else "schema tokens present",
            critical=True,
        ),
        build_case(
            "prompt-length",
            "static",
            len(template) <= MAX_PROMPT_LENGTH,
            f"length={len(template)}",
            critical=True,
        ),
        build_case(
            "prompt-injection-signature",
            "static",
            not injection,
            "injection signature present" if injection else "no injection signature",
            critical=True,
        ),
        build_case(
            "credential-solicit",
            "static",
            not credential,
            "template solicits credentials" if credential else "no credential solicitation",
            critical=True,
        ),
    ]


def dataset_cases(examples: list[dict[str, Any]]) -> list[EvalCaseResult]:
    texts = [str(item.get("text") or "").strip() for item in examples]
    routes = [str(item.get("expected_route") or "") for item in examples]
    nonempty = [text for text in texts if text]
    unique_texts = {text.casefold() for text in nonempty}
    route_counts = Counter(routes)
    return [
        build_case(
            "dataset-size",
            "dataset",
            len(nonempty) >= MIN_VERIFIED_EXAMPLES,
            f"verified_examples={len(nonempty)} min={MIN_VERIFIED_EXAMPLES}",
            critical=False,
        ),
        build_case(
            "dataset-duplicates",
            "dataset",
            len(unique_texts) == len(nonempty),
            f"unique={len(unique_texts)} total={len(nonempty)}",
            critical=False,
        ),
        build_case(
            "dataset-route-coverage",
            "dataset",
            len(route_counts) >= 2 or len(nonempty) < MIN_VERIFIED_EXAMPLES,
            f"routes={dict(route_counts)}",
            critical=False,
        ),
    ]


def tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w\u3400-\u9fff]+", text.casefold()) if len(token) >= 2}


def predict_route_label(
    text: str,
    training: list[dict[str, Any]],
) -> tuple[str, str]:
    query = tokenize(text)
    best_score = -1.0
    best_route = "UNKNOWN"
    best_label = "UNKNOWN"
    for item in training:
        tokens = tokenize(str(item.get("text") or ""))
        if not tokens:
            continue
        score = len(query & tokens) / max(1, len(query | tokens))
        if score > best_score:
            best_score = score
            best_route = str(item.get("expected_route") or "UNKNOWN")
            best_label = str(item.get("label") or "UNKNOWN")
    return best_route, best_label


def macro_f1(pairs: list[tuple[str, str]]) -> float:
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


def dataset_similarity_cases(
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
        predicted_route, predicted_label = predict_route_label(text, training)
        route_pairs.append((expected_route, predicted_route))
        label_pairs.append((expected_label, predicted_label))
        results.append(
            build_case(
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
    return results, accuracy, route_accuracy, macro_f1(route_pairs)


def estimate_cost_usd(*, template: str, examples: list[dict[str, Any]]) -> float:
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


def estimate_latency_ms(*, template: str, examples: list[dict[str, Any]]) -> float:
    per_example = 40 + len(template) // 120
    return float(max(20, per_example * max(1, len(examples))))
