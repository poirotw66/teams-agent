"""Shared release-gate check contract for knowledge / FAQ activation paths.

Publish and activate entry points must consult this checker before flipping an
active pointer so ``/activate-target`` is not the only gated path (Spec 7.1).

The protocol and blocked error live in ``platform_kernel``. Backoffice-specific
adapters live under ``ai_ops_backoffice.adapters``.
"""

from __future__ import annotations

from typing import Any

from platform_kernel.ports.release_gate import (
    ReleaseGateBlockedError,
    ReleaseGateChecker,
)

__all__ = [
    "ReleaseGateBlockedError",
    "ReleaseGateChecker",
    "require_release_gate",
]


def require_release_gate(
    checker: ReleaseGateChecker | None,
    *,
    target_manifest_hash: str,
    target_type: str,
    policy_id: str = "default-gate-policy",
    tenant_id: str | None = None,
    environment: str = "prod",
    policy_version: int | None = None,
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
        tenant_id=tenant_id,
        environment=environment,
        policy_version=policy_version,
    )
