from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_service.target_manifest import calculate_target_manifest_hash

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
        blocking_errors: list[str] = []
        warnings: list[str] = []
        limits = limits or {}

        # 1. Validate Set Version
        set_version = self._repo.get_set_version(set_version_id)
        if not set_version:
            blocking_errors.append(f"Eval set version not found: {set_version_id}")
            return RunPreflightResult(
                is_valid=False,
                blocking_errors=tuple(blocking_errors),
                warnings=tuple(warnings),
                is_eval_eligible=False,
            )

        if set_version.status != "PUBLISHED":
            warnings.append(
                f"Set version {set_version.version} is {set_version.status}, not PUBLISHED"
            )

        case_count = len(set_version.case_revision_ids)
        if case_count == 0:
            blocking_errors.append("Eval set version contains 0 case revisions")

        # 2. Resolve Baseline and Candidate Manifests
        baseline_manifest, b_errs = self.resolve_manifest(baseline_target, "BASELINE")
        candidate_manifest, c_errs = self.resolve_manifest(candidate_target, "CANDIDATE")
        blocking_errors.extend(b_errs)
        blocking_errors.extend(c_errs)

        # 3. Enforcement for REAL_RAG execution mode (Spec 6.1, F01-T1)
        normalized_mode = mode.upper() if mode else "REAL_RAG"
        is_eval_eligible = True

        if normalized_mode == "REAL_RAG":
            if has_retriever_adapter is False or has_answering_adapter is False:
                blocking_errors.append(
                    "REAL_RAG mode requires registered real retriever and answer adapters. "
                    "Ephemeral mock or keyword fallback is prohibited for production evaluation."
                )
            # Validate pinned knowledge releases exist on disk if releases_dir is provided
            if self._releases_dir:
                if baseline_manifest.knowledge_release_id:
                    rel_b = self._releases_dir / baseline_manifest.knowledge_release_id
                    if not (rel_b / "index" / "chunks.json").is_file() and not (rel_b / "chunks.json").is_file():
                        blocking_errors.append(
                            f"Pinned baseline knowledge release artifact not found: {baseline_manifest.knowledge_release_id}"
                        )
                if candidate_manifest.knowledge_release_id:
                    rel_c = self._releases_dir / candidate_manifest.knowledge_release_id
                    if not (rel_c / "index" / "chunks.json").is_file() and not (rel_c / "chunks.json").is_file():
                        blocking_errors.append(
                            f"Pinned candidate knowledge release artifact not found: {candidate_manifest.knowledge_release_id}"
                        )
        elif normalized_mode == "AGENT_SANDBOX":
            if has_sandbox_adapter is False:
                blocking_errors.append("AGENT_SANDBOX mode requires registered agent sandbox adapter.")
        elif normalized_mode == "OFFLINE_BENCHMARK":
            is_eval_eligible = False
            warnings.append(
                "OFFLINE_BENCHMARK mode is not eligible for quality gate release enforcement (不可作真實品質發布驗收)."
            )

        # 4. Check for knowledge release configuration
        if not baseline_manifest.knowledge_release_id:
            warnings.append("Baseline has no pinned knowledge_release_id; defaulting to bundled index")
        if not candidate_manifest.knowledge_release_id:
            warnings.append("Candidate has no pinned knowledge_release_id; defaulting to bundled index")

        # 5. Check limits and cost estimation
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

        is_valid = len(blocking_errors) == 0
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
