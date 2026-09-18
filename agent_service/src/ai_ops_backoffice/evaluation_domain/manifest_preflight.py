"""REAL_RAG / sandbox mode checks for ManifestResolver.preflight_run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .runner_models import TargetManifest


def apply_mode_preflight_checks(
    *,
    mode: str,
    releases_dir: Path | None,
    baseline_manifest: TargetManifest,
    candidate_manifest: TargetManifest,
    has_retriever_adapter: bool | None,
    has_answering_adapter: bool | None,
    has_sandbox_adapter: bool | None,
    blocking_errors: list[str],
    warnings: list[str],
) -> bool:
    """Mutate error/warning lists; return is_eval_eligible."""
    normalized_mode = mode.upper() if mode else "REAL_RAG"
    is_eval_eligible = True
    if normalized_mode == "REAL_RAG":
        if has_retriever_adapter is False or has_answering_adapter is False:
            blocking_errors.append(
                "REAL_RAG mode requires registered real retriever and answer adapters. "
                "Ephemeral mock or keyword fallback is prohibited for production evaluation."
            )
        if releases_dir:
            _check_release_artifact(
                releases_dir,
                baseline_manifest.knowledge_release_id,
                "baseline",
                blocking_errors,
            )
            _check_release_artifact(
                releases_dir,
                candidate_manifest.knowledge_release_id,
                "candidate",
                blocking_errors,
            )
    elif normalized_mode == "AGENT_SANDBOX":
        if has_sandbox_adapter is False:
            blocking_errors.append(
                "AGENT_SANDBOX mode requires registered agent sandbox adapter."
            )
    elif normalized_mode == "OFFLINE_BENCHMARK":
        is_eval_eligible = False
        warnings.append(
            "OFFLINE_BENCHMARK mode is not eligible for quality gate release enforcement "
            "(不可作真實品質發布驗收)."
        )
    return is_eval_eligible


def _check_release_artifact(
    releases_dir: Path,
    release_id: str | None,
    side: str,
    blocking_errors: list[str],
) -> None:
    if not release_id:
        return
    rel = releases_dir / release_id
    if not (rel / "index" / "chunks.json").is_file() and not (
        rel / "chunks.json"
    ).is_file():
        blocking_errors.append(
            f"Pinned {side} knowledge release artifact not found: {release_id}"
        )


def estimate_preflight_cost(
    *,
    case_count: int,
    limits: dict[str, Any],
    warnings: list[str],
) -> tuple[int, float, float]:
    max_cases = limits.get("max_cases")
    effective_cases = min(case_count, max_cases) if max_cases else case_count
    estimated_tokens = effective_cases * 2 * 1200
    estimated_cost_usd = round(estimated_tokens * 0.0000003, 4)
    estimated_duration_seconds = round(effective_cases * 2 * 1.5, 1)
    max_cost_usd = limits.get("max_cost_usd")
    if max_cost_usd and estimated_cost_usd > max_cost_usd:
        warnings.append(
            f"Estimated cost (${estimated_cost_usd}) exceeds requested limit (${max_cost_usd})"
        )
    return effective_cases, estimated_cost_usd, estimated_duration_seconds
