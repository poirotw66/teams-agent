"""Request-scoped policy snapshots and providers for ops runtime."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent_service.operations.contracts import MASKING_POLICY_VERSION
from agent_service.operations.masking_rules import MaskingRulePack, resolve_masking_pack
from agent_service.operations.settings import OpsSettings

logger = logging.getLogger(__name__)

_RESOLVE_DEPTH: ContextVar[int] = ContextVar("policy_resolve_depth", default=0)
_SNAPSHOT: ContextVar[object | None] = ContextVar("policy_snapshot", default=None)


class PolicySourceUnavailableError(RuntimeError):
    """Governance policy source failed; callers must not silently relax controls."""


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
    """Resolve ACTIVE retention/masking; fail closed when governance is configured."""

    def __init__(
        self,
        *,
        settings: OpsSettings,
        governance: GovernancePolicySource | None = None,
        require_governance: bool | None = None,
    ) -> None:
        self._settings = settings
        self._governance = governance
        # When a governance source is wired, peek failures must not silently
        # fall back to a more permissive policy.
        self._require_governance = (
            require_governance if require_governance is not None else governance is not None
        )

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
        token = _RESOLVE_DEPTH.set(_RESOLVE_DEPTH.get() + 1)
        try:
            if self._governance is not None:
                try:
                    peeked = self._governance.peek_runtime_retention(policy_id)
                except Exception as exc:
                    if self._require_governance:
                        raise PolicySourceUnavailableError(
                            f"governance retention peek failed: {type(exc).__name__}"
                        ) from exc
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
            _RESOLVE_DEPTH.reset(token)

    def masking(self) -> EffectiveMaskingPolicy:
        token = _RESOLVE_DEPTH.set(_RESOLVE_DEPTH.get() + 1)
        try:
            if self._governance is not None:
                try:
                    peeked = self._governance.peek_runtime_masking()
                except Exception as exc:
                    if self._require_governance:
                        raise PolicySourceUnavailableError(
                            f"governance masking peek failed: {type(exc).__name__}"
                        ) from exc
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
                        except KeyError as exc:
                            if self._require_governance:
                                raise PolicySourceUnavailableError(
                                    f"unknown masking policy version {version}"
                                ) from exc
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
            _RESOLVE_DEPTH.reset(token)


_POLICY_RUNTIME: RuntimePolicyProvider | None = None


def configure_policy_runtime(runtime: RuntimePolicyProvider | None) -> None:
    global _POLICY_RUNTIME
    _POLICY_RUNTIME = runtime


def get_policy_runtime() -> RuntimePolicyProvider | None:
    return _POLICY_RUNTIME


def bind_policy_snapshot(snapshot: PolicySnapshot | None) -> Token:
    """Bind a per-request snapshot; returns a ContextVar token for reset."""
    return _SNAPSHOT.set(snapshot)


def reset_policy_snapshot(token: Token) -> None:
    _SNAPSHOT.reset(token)


@contextmanager
def policy_snapshot_scope(snapshot: PolicySnapshot | None) -> Iterator[PolicySnapshot | None]:
    """Bind a snapshot for the current async task / request context."""
    token = bind_policy_snapshot(snapshot)
    try:
        yield snapshot
    finally:
        reset_policy_snapshot(token)


def current_policy_snapshot() -> PolicySnapshot | None:
    value = _SNAPSHOT.get()
    return value if isinstance(value, PolicySnapshot) else None


def active_retention_days(settings: OpsSettings) -> int:
    if _RESOLVE_DEPTH.get() > 0:
        return settings.default_retention_days
    snapshot = current_policy_snapshot()
    if snapshot is not None:
        return snapshot.retention.ttl_days
    runtime = get_policy_runtime()
    if runtime is None:
        return settings.default_retention_days
    return runtime.retention().ttl_days


def active_masking_policy() -> EffectiveMaskingPolicy:
    if _RESOLVE_DEPTH.get() > 0:
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
    import os

    store_mode = (os.environ.get("AI_OPS_GOVERNANCE_STORE_MODE", "FILE") or "FILE").upper()
    try:
        from ai_ops_backoffice.governance_domain.service import GovernanceService
        from ai_ops_backoffice.governance_domain.store_factory import (
            SUPPORTED_GOVERNANCE_STORE_MODES,
            build_governance_repository,
        )
    except Exception:  # noqa: BLE001
        logger.warning("governance packages unavailable; policy runtime uses defaults")
        return None
    if store_mode not in SUPPORTED_GOVERNANCE_STORE_MODES:
        logger.warning("unsupported governance store mode %s; using defaults", store_mode)
        return None
    path = Path(
        os.environ.get(
            "AI_OPS_GOVERNANCE_STORE_PATH",
            str(settings.store_path.parent / "phase3" / "governance.json"),
        )
    )
    project = os.environ.get("AI_OPS_GCP_PROJECT") or settings.firestore_project
    collection = (
        os.environ.get("AI_OPS_GOVERNANCE_FIRESTORE_COLLECTION") or "ai_ops_governance_state"
    )
    try:
        repository = build_governance_repository(
            store_mode=store_mode,
            file_path=path,
            firestore_project=project,
            firestore_collection=collection,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "governance repository unavailable (%s); policy runtime uses defaults",
            type(exc).__name__,
        )
        return None
    return GovernanceService(repository)
