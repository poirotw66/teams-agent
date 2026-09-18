from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_core.target_manifest import calculate_target_manifest_hash

from .repository import EvaluationRepository
from .runner_models import RunPreflightResult, TargetManifest, TargetSide

__all__ = [
    "ManifestResolver",
    "calculate_target_manifest_hash",
]


class ManifestResolver:
    """Resolves and validates TargetManifests against pinned artifacts and releases."""

    def __init__(
        self,
        repository: EvaluationRepository,
        releases_dir: Path | None = None,
    ) -> None:
        self._repo = repository
        self._releases_dir = releases_dir

    def resolve_manifest(
        self,
        target_ref: dict[str, Any],
        side: TargetSide,
    ) -> tuple[TargetManifest, list[str]]:
        """Resolves target reference into TargetManifest and returns any blocking errors."""
        blocking_errors: list[str] = []
        target_id = target_ref.get("target_id") or f"{side.lower()}_target"
        knowledge_release_id = target_ref.get("knowledge_release_id")

        # Validate pinned knowledge release artifact existence if releases_dir is configured
        if knowledge_release_id and self._releases_dir:
            index_file = self._releases_dir / knowledge_release_id / "index" / "chunks.json"
            if not index_file.is_file():
                blocking_errors.append(
                    f"Pinned knowledge release artifact not found: {knowledge_release_id}"
                )

        manifest_dict = {
            "target_id": target_id,
            "target_side": side,
            "app_revision": target_ref.get("app_revision", "v1"),
            "prompt_version": target_ref.get("prompt_version", "default"),
            "model_id": target_ref.get("model_id", "gemini-3.8-flash"),
            "temperature": float(target_ref.get("temperature", 0.0)),
            "knowledge_release_id": knowledge_release_id,
            "faq_version_id": target_ref.get("faq_version_id"),
            "retriever_config": target_ref.get("retriever_config", {}),
            "persona_fixture_id": target_ref.get("persona_fixture_id"),
            "acl_policy": target_ref.get("acl_policy", "STRICT"),
            "environment": target_ref.get("environment", "test"),
        }
        manifest_hash = calculate_target_manifest_hash(manifest_dict)
        manifest = TargetManifest(**manifest_dict, manifest_hash=manifest_hash)
        return manifest, blocking_errors

    def preflight_run(
        self,
        set_version_id: str,
        baseline_target: dict[str, Any],
        candidate_target: dict[str, Any],
        limits: dict[str, Any] | None = None,
        mode: str = "REAL_RAG",
        has_retriever_adapter: bool | None = None,
        has_answering_adapter: bool | None = None,
        has_sandbox_adapter: bool | None = None,
    ) -> RunPreflightResult:
        """Performs preflight checks before an evaluation run is queued (Spec 6.1)."""
        from .manifest_preflight import apply_mode_preflight_checks, estimate_preflight_cost

        blocking_errors: list[str] = []
        warnings: list[str] = []
        limits = limits or {}
        set_version = self._repo.get_set_version(set_version_id)
        if not set_version:
            return RunPreflightResult(
                is_valid=False,
                blocking_errors=(f"Eval set version not found: {set_version_id}",),
                warnings=(),
                is_eval_eligible=False,
            )
        if set_version.status != "PUBLISHED":
            warnings.append(
                f"Set version {set_version.version} is {set_version.status}, not PUBLISHED"
            )
        case_count = len(set_version.case_revision_ids)
        if case_count == 0:
            blocking_errors.append("Eval set version contains 0 case revisions")
        baseline_manifest, b_errs = self.resolve_manifest(baseline_target, "BASELINE")
        candidate_manifest, c_errs = self.resolve_manifest(candidate_target, "CANDIDATE")
        blocking_errors.extend(b_errs + c_errs)
        is_eval_eligible = apply_mode_preflight_checks(
            mode=mode,
            releases_dir=self._releases_dir,
            baseline_manifest=baseline_manifest,
            candidate_manifest=candidate_manifest,
            has_retriever_adapter=has_retriever_adapter,
            has_answering_adapter=has_answering_adapter,
            has_sandbox_adapter=has_sandbox_adapter,
            blocking_errors=blocking_errors,
            warnings=warnings,
        )
        if not baseline_manifest.knowledge_release_id:
            warnings.append(
                "Baseline has no pinned knowledge_release_id; defaulting to bundled index"
            )
        if not candidate_manifest.knowledge_release_id:
            warnings.append(
                "Candidate has no pinned knowledge_release_id; defaulting to bundled index"
            )
        effective_cases, estimated_cost_usd, estimated_duration_seconds = (
            estimate_preflight_cost(
                case_count=case_count, limits=limits, warnings=warnings
            )
        )
        is_valid = not blocking_errors
        return RunPreflightResult(
            is_valid=is_valid,
            blocking_errors=tuple(blocking_errors),
            warnings=tuple(warnings),
            resolved_baseline_manifest=baseline_manifest if is_valid else None,
            resolved_candidate_manifest=candidate_manifest if is_valid else None,
            case_count=effective_cases,
            estimated_cost_usd=estimated_cost_usd,
            estimated_duration_seconds=estimated_duration_seconds,
            is_eval_eligible=is_eval_eligible,
        )
