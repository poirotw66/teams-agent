"""GateEvaluator: release-gate decisions from evaluation run summaries."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from .gate_checks import collect_blocking_reasons
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
        now = datetime.now(timezone.utc)
        blocking_reasons, metrics_snapshot, is_eligible = collect_blocking_reasons(
            policy_version=policy_version,
            run=run,
            target_manifest_hash=target_manifest_hash,
        )

        decision_status = "PASS" if not blocking_reasons else "FAIL"
        valid_until = now + timedelta(hours=policy_version.validity_hours)
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
