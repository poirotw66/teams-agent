"""Request-scoped policy snapshots and providers for ops runtime."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_service.operations.contracts import MASKING_POLICY_VERSION
from agent_service.operations.masking_rules import MaskingRulePack, resolve_masking_pack
from agent_service.operations.settings import OpsSettings

logger = logging.getLogger(__name__)

_RESOLVE_DEPTH = threading.local()
_SNAPSHOT: threading.local = threading.local()


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
    rules_hash: str
    pack: MaskingRulePack
    source: str
    version_id: str | None = None


@dataclass(frozen=True)
class PolicySnapshot:
    """Consistent retention + masking view for one request/worker cycle."""

    retention: EffectiveRetentionPolicy
    masking: EffectiveMaskingPolicy


class RuntimePolicyProvider(Protocol):
    def snapshot(self, *, policy_id: str = "operational-events") -> PolicySnapshot: ...

    def retention(
        self, *, policy_id: str = "operational-events"
    ) -> EffectiveRetentionPolicy: ...

    def masking(self) -> EffectiveMaskingPolicy: ...


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

    def snapshot(self, *, policy_id: str = "operational-events") -> PolicySnapshot:
        return PolicySnapshot(
            retention=self.retention(policy_id=policy_id),
            masking=self.masking(),
        )

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
                    rules_hash = str(peeked.get("rulesHash") or "").strip()
                    if version:
                        try:
                            pack = resolve_masking_pack(version)
                        except KeyError:
                            logger.warning(
                                "unknown masking policy version %s; using code baseline",
                                version,
                            )
                            pack = resolve_masking_pack(MASKING_POLICY_VERSION)
                            return EffectiveMaskingPolicy(
                                policy_version=pack.policy_version,
                                rules_hash=pack.rules_hash,
                                pack=pack,
                                source="code_baseline_fallback",
                                version_id=str(peeked.get("versionId") or "") or None,
                            )
                        if rules_hash and rules_hash != pack.rules_hash:
                            logger.warning(
                                "masking rules_hash mismatch for %s "
                                "(stored=%s computed=%s); using computed pack",
                                version,
                                rules_hash,
                                pack.rules_hash,
                            )
                        return EffectiveMaskingPolicy(
                            policy_version=pack.policy_version,
                            rules_hash=pack.rules_hash,
                            pack=pack,
                            source="governance",
                            version_id=str(peeked.get("versionId") or "") or None,
                        )
            pack = resolve_masking_pack(MASKING_POLICY_VERSION)
            return EffectiveMaskingPolicy(
                policy_version=pack.policy_version,
                rules_hash=pack.rules_hash,
                pack=pack,
                source="code_baseline",
            )
        finally:
            _exit_resolve()


_POLICY_RUNTIME: RuntimePolicyProvider | None = None


def configure_policy_runtime(runtime: RuntimePolicyProvider | None) -> None:
    global _POLICY_RUNTIME
    _POLICY_RUNTIME = runtime


def get_policy_runtime() -> RuntimePolicyProvider | None:
    return _POLICY_RUNTIME


def bind_policy_snapshot(snapshot: PolicySnapshot | None) -> None:
    """Bind a per-request snapshot; clears when ``None``."""
    _SNAPSHOT.value = snapshot


def current_policy_snapshot() -> PolicySnapshot | None:
    return getattr(_SNAPSHOT, "value", None)


def active_retention_days(settings: OpsSettings) -> int:
    if _resolve_depth() > 0:
        return settings.default_retention_days
    snapshot = current_policy_snapshot()
    if snapshot is not None:
        return snapshot.retention.ttl_days
    runtime = get_policy_runtime()
    if runtime is None:
        return settings.default_retention_days
    return runtime.retention().ttl_days


def active_masking_policy() -> EffectiveMaskingPolicy:
    if _resolve_depth() > 0:
        pack = resolve_masking_pack(MASKING_POLICY_VERSION)
        return EffectiveMaskingPolicy(
            policy_version=pack.policy_version,
            rules_hash=pack.rules_hash,
            pack=pack,
            source="code_baseline",
        )
    snapshot = current_policy_snapshot()
    if snapshot is not None:
        return snapshot.masking
    runtime = get_policy_runtime()
    if runtime is None:
        pack = resolve_masking_pack(MASKING_POLICY_VERSION)
        return EffectiveMaskingPolicy(
            policy_version=pack.policy_version,
            rules_hash=pack.rules_hash,
            pack=pack,
            source="code_baseline",
        )
    return runtime.masking()


def active_masking_policy_version() -> str:
    return active_masking_policy().policy_version


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
