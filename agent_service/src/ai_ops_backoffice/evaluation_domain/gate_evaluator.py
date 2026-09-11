from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from .gate_models import GateDecision, GatePolicyVersion
from .runner_models import EvaluationRun


class GateEvaluator:
    """Evaluates evaluation runs against release gate policy criteria to yield immutable decisions."""

    def evaluate(
        self,
        *,
        policy_version: GatePolicyVersion,
        run: EvaluationRun,
        target_manifest_hash: str,
    ) -> GateDecision:
        blocking_reasons: list[str] = []
        now = datetime.now(timezone.utc)

        # 1. Target manifest match check
        if run.candidate_manifest.manifest_hash != target_manifest_hash:
            blocking_reasons.append(
                f"Candidate manifest hash mismatch: target requires '{target_manifest_hash}', "
                f"but run evaluated '{run.candidate_manifest.manifest_hash}'"
            )

        # 2. Required set version check
        if policy_version.required_set_version_ids:
            if run.set_version_id not in policy_version.required_set_version_ids:
                blocking_reasons.append(
                    f"Set version '{run.set_version_id}' is not in policy required set versions "
                    f"{list(policy_version.required_set_version_ids)}"
                )

        summary = run.summary
        if summary is None:
            blocking_reasons.append("Evaluation run has no summary results")
            metrics_snapshot = {}
        else:
            metrics_snapshot = summary.model_dump(mode="json")

            # 3. Minimum coverage check
            if summary.coverage < policy_version.minimum_coverage:
                blocking_reasons.append(
                    f"Execution coverage {summary.coverage:.1%} is below required {policy_version.minimum_coverage:.1%}"
                )

            # 4. Critical failure check
            if policy_version.critical_rule == "ZERO_TOLERANCE":
                if len(summary.critical_failures) > 0:
                    blocking_reasons.append(
                        f"Zero tolerance rule violated: {len(summary.critical_failures)} critical failure(s) "
                        f"({', '.join(summary.critical_failures)})"
                    )

            # 5. Minimum pass rate check
            pass_rate = summary.pass_rate if summary.pass_rate is not None else 0.0
            if pass_rate < policy_version.minimum_pass_rate:
                blocking_reasons.append(
                    f"Candidate pass rate {pass_rate:.1%} is below minimum threshold {policy_version.minimum_pass_rate:.1%}"
                )

            # 6. Regressions check
            if len(summary.regressions) > policy_version.max_regression_count:
                blocking_reasons.append(
                    f"Detected {len(summary.regressions)} regressions against baseline, "
                    f"exceeding max allowed {policy_version.max_regression_count}"
                )

            # 7. Inconclusive cases check
            if len(summary.inconclusive_cases) > 0:
                blocking_reasons.append(
                    f"Run contains {len(summary.inconclusive_cases)} inconclusive/unjudged case(s)"
                )

            # 8. Budget and latency limits
            if policy_version.max_cost_usd is not None and summary.actual_cost_usd > policy_version.max_cost_usd:
                blocking_reasons.append(
                    f"Actual cost ${summary.actual_cost_usd:.4f} exceeds limit ${policy_version.max_cost_usd:.4f}"
                )

            if (
                policy_version.max_latency_p95_ms is not None
                and summary.latency_p95_ms > policy_version.max_latency_p95_ms
            ):
                blocking_reasons.append(
                    f"P95 latency {summary.latency_p95_ms:.1f}ms exceeds limit {policy_version.max_latency_p95_ms:.1f}ms"
                )

        # 9. Ineligible evaluation run check (Spec 6.1, F01-T1, F05-T2)
        is_eligible = getattr(run, "is_eval_eligible", True)
        if not is_eligible:
            blocking_reasons.append(
                "Evaluation run is marked ineligible for quality gate release "
                "(e.g. OFFLINE_BENCHMARK or missing formal adapters)"
            )

        decision_status = "PASS" if not blocking_reasons else "FAIL"
        valid_until = now + timedelta(hours=policy_version.validity_hours)

        import hashlib
        import json
        digest_data = {
            "run_id": run.run_id,
            "manifest_hash": target_manifest_hash,
            "metrics": metrics_snapshot,
            "blocking_reasons": sorted(blocking_reasons),
        }
        result_digest = hashlib.sha256(
            json.dumps(digest_data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        return GateDecision(
            decision_id=f"gdec_{uuid.uuid4().hex[:12]}",
            policy_id=policy_version.policy_id,
            policy_version=policy_version.version,
            run_id=run.run_id,
            target_manifest_hash=target_manifest_hash,
            decision=decision_status,
            mode_at_evaluation=policy_version.mode,
            tenant_id=getattr(run, "tenant_id", "default") or "default",
            suite_versions=(run.set_version_id,),
            run_ids=(run.run_id,),
            result_digest=result_digest,
            blocking_reasons=tuple(blocking_reasons),
            metrics_snapshot=metrics_snapshot,
            valid_until=valid_until,
            is_valid=True,
            is_eval_eligible=is_eligible,
            created_at=now,
        )
