from __future__ import annotations

import re
import uuid
from collections import Counter
from typing import Any

from .constants import INJECTION_SIGNATURES, MAX_PROMPT_LENGTH, METRIC_VERSION, RUNNER_VERSION
from .helpers import content_hash, fingerprint
from .models import EvalCaseResult, EvalRun, PromptVersion, utc_now

SCHEMA_TOKENS = ("{max_issues}", "{faq_keys}")
CREDENTIAL_SOLICIT = re.compile(r"(?i)(ask|request|require).{0,40}(password|api key|otp|token)")


def _case(case_id: str, category: str, passed: bool, detail: str, *, critical: bool) -> EvalCaseResult:
    return EvalCaseResult(
        case_id=case_id,
        category=category,
        critical=critical,
        passed=passed,
        detail=detail,
    )


def _schema_cases(template: str) -> list[EvalCaseResult]:
    missing = [token for token in SCHEMA_TOKENS if token not in template]
    return [
        _case(
            "schema-tokens",
            "structured_output",
            not missing,
            "missing " + ", ".join(missing) if missing else "schema tokens present",
            critical=True,
        ),
        _case(
            "prompt-length",
            "structured_output",
            len(template) <= MAX_PROMPT_LENGTH,
            f"length={len(template)}",
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


def _safety_cases(template: str) -> list[EvalCaseResult]:
    lowered = template.casefold()
    injection = any(signature in lowered for signature in INJECTION_SIGNATURES)
    credential = _solicits_credentials(template)
    return [
        _case(
            "prompt-injection",
            "prompt_injection",
            not injection,
            "injection signature present" if injection else "no injection signature",
            critical=True,
        ),
        _case(
            "credential-solicit",
            "credential_leak",
            not credential,
            "template solicits credentials" if credential else "no credential solicitation",
            critical=True,
        ),
    ]


def _example_cases(template: str, examples: list[dict[str, Any]]) -> list[EvalCaseResult]:
    results: list[EvalCaseResult] = []
    for index, example in enumerate(examples):
        route = str(example.get("expected_route") or "")
        label = str(example.get("label") or "")
        present = route in template and label in template
        results.append(
            _case(
                f"example-{index}",
                "classification",
                present,
                f"{route} {label}",
                critical=False,
            )
        )
    return results


def _accuracy(results: list[EvalCaseResult], category: str) -> float:
    selected = [item for item in results if item.category == category]
    if not selected:
        return 1.0
    return sum(1 for item in selected if item.passed) / len(selected)


def _cost_usd(template: str) -> float:
    return round(len(template) / 4 * 0.000002, 8)


def _latency_ms(template: str) -> float:
    return float(max(20, len(template) // 80))


def evaluate_prompt(
    *,
    candidate: PromptVersion,
    baseline: PromptVersion | None,
    examples: list[dict[str, Any]],
    actor_id: str,
    taxonomy_version: str,
    knowledge_release_id: str | None,
) -> EvalRun:
    cases = [
        *_schema_cases(candidate.template),
        *_safety_cases(candidate.template),
        *_example_cases(candidate.template, examples),
    ]
    accuracy = _accuracy(cases, "classification")
    baseline_accuracy = _accuracy(
        _example_cases(baseline.template, examples), "classification"
    ) if baseline else None
    cost = _cost_usd(candidate.template)
    baseline_cost = _cost_usd(baseline.template) if baseline else None
    quality_passed = True
    if baseline_accuracy is not None and accuracy + 1e-9 < baseline_accuracy:
        quality_passed = False
    if baseline_cost is not None and cost > baseline_cost * 2:
        quality_passed = False
    critical_passed = all(item.passed for item in cases if item.critical)
    now = utc_now()
    manifest = fingerprint(
        {
            "dataset": candidate.dataset_version,
            "taxonomy": taxonomy_version,
            "knowledge": knowledge_release_id,
            "model": candidate.model_id,
            "runner": RUNNER_VERSION,
            "metric": METRIC_VERSION,
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
        status="COMPLETED",
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
        latency_ms=_latency_ms(candidate.template),
        baseline_latency_ms=_latency_ms(baseline.template) if baseline else None,
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
