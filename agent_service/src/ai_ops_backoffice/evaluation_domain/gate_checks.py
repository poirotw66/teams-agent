"""Release-gate blocking-reason checks for GateEvaluator."""

from __future__ import annotations

from typing import Any

from .gate_models import GatePolicyVersion
from .runner_models import EvaluationRun


def collect_blocking_reasons(
    *,
    policy_version: GatePolicyVersion,
    run: EvaluationRun,
    target_manifest_hash: str,
) -> tuple[list[str], dict[str, Any], bool]:
    blocking_reasons: list[str] = []

    if run.candidate_manifest.manifest_hash != target_manifest_hash:
        blocking_reasons.append(
            f"Candidate manifest hash mismatch: target requires '{target_manifest_hash}', "
            f"but run evaluated '{run.candidate_manifest.manifest_hash}'"
        )

    if policy_version.required_set_version_ids:
        if run.set_version_id not in policy_version.required_set_version_ids:
            blocking_reasons.append(
                f"Set version '{run.set_version_id}' is not in policy required set versions "
                f"{list(policy_version.required_set_version_ids)}"
            )

    summary = run.summary
    if summary is None:
        blocking_reasons.append("Evaluation run has no summary results")
        metrics_snapshot: dict[str, Any] = {}
    else:
        metrics_snapshot = summary.model_dump(mode="json")
        append_summary_blocking_reasons(
            blocking_reasons,
            policy_version=policy_version,
            summary=summary,
        )

    is_eligible = getattr(run, "is_eval_eligible", True)
    if not is_eligible:
        blocking_reasons.append(
            "Evaluation run is marked ineligible for quality gate release "
            "(e.g. OFFLINE_BENCHMARK or missing formal adapters)"
        )

    return blocking_reasons, metrics_snapshot, bool(is_eligible)


def append_summary_blocking_reasons(
    blocking_reasons: list[str],
    *,
    policy_version: GatePolicyVersion,
    summary: Any,
) -> None:
    if summary.coverage < policy_version.minimum_coverage:
        blocking_reasons.append(
            f"Execution coverage {summary.coverage:.1%} is below required "
            f"{policy_version.minimum_coverage:.1%}"
        )

    if policy_version.critical_rule == "ZERO_TOLERANCE":
        if len(summary.critical_failures) > 0:
            blocking_reasons.append(
                f"Zero tolerance rule violated: {len(summary.critical_failures)} critical "
                f"failure(s) ({', '.join(summary.critical_failures)})"
            )

    pass_rate = summary.pass_rate if summary.pass_rate is not None else 0.0
    if pass_rate < policy_version.minimum_pass_rate:
        blocking_reasons.append(
            f"Candidate pass rate {pass_rate:.1%} is below minimum threshold "
            f"{policy_version.minimum_pass_rate:.1%}"
        )

    if len(summary.regressions) > policy_version.max_regression_count:
        blocking_reasons.append(
            f"Detected {len(summary.regressions)} regressions against baseline, "
            f"exceeding max allowed {policy_version.max_regression_count}"
        )

    if len(summary.inconclusive_cases) > 0:
        blocking_reasons.append(
            f"Run contains {len(summary.inconclusive_cases)} inconclusive/unjudged case(s)"
        )

    if (
        policy_version.max_cost_usd is not None
        and summary.actual_cost_usd > policy_version.max_cost_usd
    ):
        blocking_reasons.append(
            f"Actual cost ${summary.actual_cost_usd:.4f} exceeds limit "
            f"${policy_version.max_cost_usd:.4f}"
        )

    if (
        policy_version.max_latency_p95_ms is not None
        and summary.latency_p95_ms > policy_version.max_latency_p95_ms
    ):
        blocking_reasons.append(
            f"P95 latency {summary.latency_p95_ms:.1f}ms exceeds limit "
            f"{policy_version.max_latency_p95_ms:.1f}ms"
        )
