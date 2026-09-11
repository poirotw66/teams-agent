"""Shared release-gate check contract for knowledge / FAQ activation paths.

Publish and activate entry points must consult this checker before flipping an
active pointer so ``/activate-target`` is not the only gated path (Spec 7.1).
"""

from __future__ import annotations

from typing import Any, Protocol


class ReleaseGateBlockedError(Exception):
    """Raised when an ENFORCE gate blocks activation or publish."""


class ReleaseGateChecker(Protocol):
    def check_activation(
        self,
        *,
        target_manifest_hash: str,
        target_type: str,
        policy_id: str = "default-gate-policy",
    ) -> dict[str, Any]:
        """Return gate status dict, or raise ReleaseGateBlockedError when blocked."""
        ...


class QualityGateReleaseChecker:
    """Adapts QualityGateService.verify_release_gate into the shared checker."""

    def __init__(self, gate_service: Any) -> None:
        self._gate_service = gate_service

    def check_activation(
        self,
        *,
        target_manifest_hash: str,
        target_type: str,
        policy_id: str = "default-gate-policy",
    ) -> dict[str, Any]:
        from ai_ops_backoffice.evaluation_domain.gate_service import GateBlockedError

        try:
            result = self._gate_service.verify_release_gate(
                target_manifest_hash=target_manifest_hash,
                policy_id=policy_id,
            )
        except GateBlockedError as exc:
            raise ReleaseGateBlockedError(str(exc)) from exc
        return {**result, "target_type": target_type}


def require_release_gate(
    checker: ReleaseGateChecker | None,
    *,
    target_manifest_hash: str,
    target_type: str,
    policy_id: str = "default-gate-policy",
) -> dict[str, Any] | None:
    """Invoke checker when present.

    Missing checker is treated as REPORT_ONLY allow for local/dev unit tests that
    do not wire QualityGateService. When a checker IS injected, ENFORCE mode must
    fail closed via ReleaseGateBlockedError (matching QualityGateService semantics).
    """
    if checker is None:
        return None
    return checker.check_activation(
        target_manifest_hash=target_manifest_hash,
        target_type=target_type,
        policy_id=policy_id,
    )
