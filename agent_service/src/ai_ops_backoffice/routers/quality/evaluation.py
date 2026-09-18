"""Cross-domain evaluation evidence for quality case detail views."""

from __future__ import annotations

from typing import Any

from ...evaluation_domain.errors import EvaluationDomainError
from .context import QualityRouteContext


def build_evaluation_context(
    ctx: QualityRouteContext,
    case_id: str,
    actor: Any,
) -> dict[str, object]:
    """Return cross-domain evidence for a quality case without widening its ACL."""
    result: dict[str, object] = {
        "evaluation_access": actor.has_capability("ops.evals.read"),
        "evaluation_candidates": [],
        "evaluation_runs": [],
    }
    if not result["evaluation_access"]:
        return result

    if ctx.evaluation_service is not None:
        try:
            result["evaluation_candidates"] = ctx.evaluation_service.list_cases(
                actor=actor,
                source_type="QUALITY_CASE",
                source_id=case_id,
                limit=100,
            )
        except EvaluationDomainError:
            # Quality case access must remain usable when the actor can read
            # quality data but the separate evaluation store is unavailable.
            result["evaluation_candidates"] = []

    if ctx.evaluation_run_service is not None:
        try:
            linked_runs = []
            for item in ctx.evaluation_run_service.list_runs(actor=actor):
                run = item.get("run", item)
                linked_case_id = run.get("quality_case_id") or run.get("limits", {}).get(
                    "quality_case_id"
                )
                if linked_case_id != case_id:
                    continue
                run_copy = dict(run)
                manifest_hash = (run.get("candidate_manifest") or {}).get("manifest_hash")
                if ctx.quality_gate_service is not None and manifest_hash:
                    decisions = ctx.quality_gate_service.repository.list_decisions(
                        target_manifest_hash=manifest_hash,
                    )
                    if decisions:
                        latest = max(
                            decisions,
                            key=lambda decision: decision.created_at,
                        )
                        run_copy["gate_decision"] = latest.model_dump(mode="json")
                linked_runs.append(run_copy)
            result["evaluation_runs"] = linked_runs
        except EvaluationDomainError:
            result["evaluation_runs"] = []

    return result
