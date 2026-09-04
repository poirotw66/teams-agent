"""Runtime bridge from Phase 3 ACTIVE governance policies to ops emitters."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_service.operations.contracts import MASKING_POLICY_VERSION
from agent_service.operations.settings import OpsSettings

logger = logging.getLogger(__name__)

# Governance model validators call mask_text during peek/load.  mask_text asks
# for the active masking policy version, which would otherwise re-enter peek.
_RESOLVE_DEPTH = threading.local()


def _resolve_depth() -> int:
    return int(getattr(_RESOLVE_DEPTH, "value", 0) or 0)


def _enter_resolve() -> None:
    _RESOLVE_DEPTH.value = _resolve_depth() + 1


def _exit_resolve() -> None:
    _RESOLVE_DEPTH.value = max(0, _resolve_depth() - 1)


class GovernancePolicySource(Protocol):
    def peek_runtime_retention(
        self, policy_id: str = "operational-events"
    ) -> dict[str, object] | None: ...

    def peek_runtime_masking(self) -> dict[str, object] | None: ...


@dataclass(frozen=True)
class EffectiveRetentionPolicy:
    ttl_days: int
    source: str
    version_id: str | None = None


@dataclass(frozen=True)
class EffectiveMaskingPolicy:
    policy_version: str
    source: str
    version_id: str | None = None


class PolicyRuntime:
    """Resolve ACTIVE retention/masking with fail-safe settings defaults."""

    def __init__(
        self,
        *,
        settings: OpsSettings,
        governance: GovernancePolicySource | None = None,
    ) -> None:
        self._settings = settings
        self._governance = governance

    @classmethod
    def from_ops_settings(cls, settings: OpsSettings) -> PolicyRuntime:
        return cls(settings=settings, governance=_try_build_governance(settings))

    def retention(
        self, *, policy_id: str = "operational-events"
    ) -> EffectiveRetentionPolicy:
        _enter_resolve()
        try:
            if self._governance is not None:
                try:
                    peeked = self._governance.peek_runtime_retention(policy_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "governance retention peek failed (%s); using settings default",
                        type(exc).__name__,
                    )
                    peeked = None
                if peeked is not None:
                    ttl = int(peeked["ttlDays"])
                    if ttl >= 1:
                        return EffectiveRetentionPolicy(
                            ttl_days=ttl,
                            source="governance",
                            version_id=str(peeked.get("versionId") or "") or None,
                        )
            return EffectiveRetentionPolicy(
                ttl_days=self._settings.default_retention_days,
                source="settings_baseline",
            )
        finally:
            _exit_resolve()

    def masking(self) -> EffectiveMaskingPolicy:
        _enter_resolve()
        try:
            if self._governance is not None:
                try:
                    peeked = self._governance.peek_runtime_masking()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "governance masking peek failed (%s); using code baseline",
                        type(exc).__name__,
                    )
                    peeked = None
                if peeked is not None:
                    version = str(peeked.get("policyVersion") or "").strip()
                    if version:
                        return EffectiveMaskingPolicy(
                            policy_version=version,
                            source="governance",
                            version_id=str(peeked.get("versionId") or "") or None,
                        )
            return EffectiveMaskingPolicy(
                policy_version=MASKING_POLICY_VERSION,
                source="code_baseline",
            )
        finally:
            _exit_resolve()


_POLICY_RUNTIME: PolicyRuntime | None = None


def configure_policy_runtime(runtime: PolicyRuntime | None) -> None:
    global _POLICY_RUNTIME
    _POLICY_RUNTIME = runtime


def get_policy_runtime() -> PolicyRuntime | None:
    return _POLICY_RUNTIME


def active_retention_days(settings: OpsSettings) -> int:
    if _resolve_depth() > 0:
        return settings.default_retention_days
    runtime = get_policy_runtime()
    if runtime is None:
        return settings.default_retention_days
    return runtime.retention().ttl_days


def active_masking_policy_version() -> str:
    if _resolve_depth() > 0:
        return MASKING_POLICY_VERSION
    runtime = get_policy_runtime()
    if runtime is None:
        return MASKING_POLICY_VERSION
    return runtime.masking().policy_version


def _try_build_governance(settings: OpsSettings) -> GovernancePolicySource | None:
    store_mode = (
        __import__("os").environ.get("AI_OPS_GOVERNANCE_STORE_MODE", "FILE") or "FILE"
    ).upper()
    if store_mode == "FILE":
        from ai_ops_backoffice.governance_domain.repository import FileGovernanceRepository
        from ai_ops_backoffice.governance_domain.service import GovernanceService

        path = Path(
            __import__("os").environ.get(
                "AI_OPS_GOVERNANCE_STORE_PATH",
                str(settings.store_path.parent / "phase3" / "governance.json"),
            )
        )
        return GovernanceService(FileGovernanceRepository(path))
    if store_mode == "FIRESTORE":
        try:
            from google.cloud import firestore

            from ai_ops_backoffice.governance_domain.repository import (
                FirestoreGovernanceRepository,
            )
            from ai_ops_backoffice.governance_domain.service import GovernanceService
        except Exception:  # noqa: BLE001
            logger.warning("firestore governance unavailable; policy runtime uses defaults")
            return None
        project = __import__("os").environ.get("AI_OPS_GCP_PROJECT") or settings.firestore_project
        collection = (
            __import__("os").environ.get("AI_OPS_GOVERNANCE_FIRESTORE_COLLECTION")
            or "ai_ops_governance_state"
        )
        return GovernanceService(
            FirestoreGovernanceRepository(
                firestore.Client(project=project) if project else firestore.Client(),
                collection=collection,
            )
        )
    return None
