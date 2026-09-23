"""Fail-closed gate for cloud formal knowledge publish/write.

Local sandbox workspaces may still publish to a local Portal. Cloud formal
writes require ENTRA identity, non-relaxed workflow, configured Entra IDs,
and an explicit enable flag. Until those are present, formal write
capabilities are stripped and proxy mutations are rejected.

Operator-selected LOCAL_SANDBOX / CLOUD_FORMAL can be persisted across
restarts via ``knowledge_workspace_store``; persistence never bypasses the
formal identity gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import KnowledgeBridgeError
from .knowledge_workspace_store import (
    apply_persisted_workspace_override,
    clear_knowledge_workspace_override,
    knowledge_workspace_override_path,
    save_knowledge_workspace_override,
)

# Mutations that affect the formal cloud publish / activation path.
FORMAL_CLOUD_WRITE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "knowledge.publish",
        "knowledge.catalog.approve",
        "knowledge.unpublish",
        "knowledge.rollback",
    }
)

_WORKSPACE_LOCAL = "LOCAL_SANDBOX"
_WORKSPACE_CLOUD = "CLOUD_FORMAL"


@dataclass(frozen=True)
class KnowledgeWorkspaceGate:
    workspace_mode: str
    cloud_formal_writes_allowed: bool
    block_reasons: tuple[str, ...]
    override_active: bool = False
    mode_source: str = "inferred"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "knowledgeWorkspaceMode": self.workspace_mode,
            "cloudFormalWritesAllowed": self.cloud_formal_writes_allowed,
            "cloudFormalWriteBlockReasons": list(self.block_reasons),
            "cloudFormalWriteBlockReasonLabels": humanize_block_reasons(
                self.block_reasons
            ),
            "knowledgeWorkspaceOverrideActive": self.override_active,
            "knowledgeWorkspaceModeSource": self.mode_source,
        }


def resolve_console_surface(settings: Any) -> str:
    """Return CLOUD or LOCAL for Console copy. Never changes the write gate."""
    explicit = str(getattr(settings, "console_surface", None) or "").strip().upper()
    if explicit in {"CLOUD", "LOCAL"}:
        return explicit
    if not bool(getattr(settings, "knowledge_in_process", True)):
        return "CLOUD"
    return "LOCAL"


def resolve_knowledge_workspace_mode(settings: Any) -> str:
    explicit = str(getattr(settings, "knowledge_workspace_mode", None) or "").strip().upper()
    if explicit in {_WORKSPACE_LOCAL, _WORKSPACE_CLOUD}:
        return explicit
    # Remote (non-in-process) Portal is treated as cloud-facing by default.
    if not bool(getattr(settings, "knowledge_in_process", True)):
        return _WORKSPACE_CLOUD
    return _WORKSPACE_LOCAL


def resolve_knowledge_workspace_mode_source(settings: Any) -> str:
    """Return ``override``, ``env``, ``runtime``, or ``inferred`` for operator UX."""
    if bool(getattr(settings, "knowledge_workspace_override_active", False)):
        return "override"
    current = str(getattr(settings, "knowledge_workspace_mode", None) or "").strip().upper()
    default = str(getattr(settings, "knowledge_workspace_mode_default", None) or "").strip().upper()
    if current in {_WORKSPACE_LOCAL, _WORKSPACE_CLOUD}:
        if default and current == default:
            return "env"
        if default:
            return "runtime"
        return "env"
    return "inferred"


_WORKSPACE_SWITCH_ROLES = frozenset({"SYSTEM_ADMIN", "KNOWLEDGE_ADMIN"})


def can_switch_knowledge_workspace(actor: Any) -> bool:
    role = str(getattr(actor, "role", "") or "").strip().upper()
    return role in _WORKSPACE_SWITCH_ROLES


def apply_knowledge_workspace_mode(
    settings: Any,
    mode: str,
    *,
    persist: bool = True,
    actor_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Set runtime workspace mode and optionally persist across restarts.

    Switching to CLOUD_FORMAL does **not** enable formal writes; those still
    require ``formal_identity_ready`` (ENTRA + flag + non-relaxed).
    """
    normalized = str(mode or "").strip().upper()
    if normalized not in {_WORKSPACE_LOCAL, _WORKSPACE_CLOUD}:
        raise ValueError(
            "knowledgeWorkspaceMode must be LOCAL_SANDBOX or CLOUD_FORMAL."
        )
    object.__setattr__(settings, "knowledge_workspace_mode", normalized)
    object.__setattr__(settings, "knowledge_workspace_override_active", True)
    if persist:
        save_knowledge_workspace_override(
            knowledge_workspace_override_path(settings),
            mode=normalized,
            actor_id=actor_id,
            reason=reason,
        )
    return normalized


def clear_knowledge_workspace_mode(
    settings: Any,
    *,
    persist: bool = True,
) -> str:
    """Clear durable override and restore env default (or inferred mode)."""
    default = str(getattr(settings, "knowledge_workspace_mode_default", None) or "").strip().upper()
    if default in {_WORKSPACE_LOCAL, _WORKSPACE_CLOUD}:
        object.__setattr__(settings, "knowledge_workspace_mode", default)
    else:
        object.__setattr__(settings, "knowledge_workspace_mode", None)
    object.__setattr__(settings, "knowledge_workspace_override_active", False)
    if persist:
        clear_knowledge_workspace_override(knowledge_workspace_override_path(settings))
    return resolve_knowledge_workspace_mode(settings)


def load_persisted_knowledge_workspace_mode(settings: Any) -> str | None:
    """Startup hook: apply disk override if present. Returns applied mode."""
    return apply_persisted_workspace_override(settings)


def humanize_block_reasons(reasons: tuple[str, ...] | list[str]) -> list[str]:
    """Map machine block reasons to Traditional Chinese operator copy."""
    labels = {
        "local_sandbox_workspace": "目前為本機測試工作區",
        "auth_mode_not_entra": "身分驗證模式不是 ENTRA",
        "relaxed_workflow": "仍啟用 relaxed／demo workflow",
        "entra_tenant_missing": "尚未設定 Entra tenant",
        "entra_client_missing": "尚未設定 Entra client",
        "formal_writes_flag_disabled": "尚未啟用 AI_OPS_KNOWLEDGE_CLOUD_FORMAL_WRITES",
    }
    return [labels.get(str(reason), str(reason)) for reason in reasons]


def formal_identity_ready(settings: Any) -> tuple[bool, tuple[str, ...]]:
    """Return whether the formal identity path is configured for cloud writes."""
    reasons: list[str] = []
    auth_mode = str(getattr(settings, "auth_mode", "") or "").strip().upper()
    if auth_mode != "ENTRA":
        reasons.append("auth_mode_not_entra")
    if bool(getattr(settings, "relaxed_workflow", False)):
        reasons.append("relaxed_workflow")
    if not str(getattr(settings, "entra_tenant_id", None) or "").strip():
        reasons.append("entra_tenant_missing")
    if not str(getattr(settings, "entra_client_id", None) or "").strip():
        reasons.append("entra_client_missing")
    if not bool(getattr(settings, "knowledge_cloud_formal_writes_enabled", False)):
        reasons.append("formal_writes_flag_disabled")
    return (not reasons, tuple(reasons))


def evaluate_knowledge_workspace_gate(settings: Any) -> KnowledgeWorkspaceGate:
    workspace = resolve_knowledge_workspace_mode(settings)
    source = resolve_knowledge_workspace_mode_source(settings)
    override_active = source == "override"
    if workspace == _WORKSPACE_LOCAL:
        return KnowledgeWorkspaceGate(
            workspace_mode=workspace,
            cloud_formal_writes_allowed=False,
            block_reasons=("local_sandbox_workspace",),
            override_active=override_active,
            mode_source=source,
        )
    ready, reasons = formal_identity_ready(settings)
    return KnowledgeWorkspaceGate(
        workspace_mode=workspace,
        cloud_formal_writes_allowed=ready,
        block_reasons=() if ready else reasons,
        override_active=override_active,
        mode_source=source,
    )


def filter_knowledge_capabilities_for_workspace(
    capabilities: frozenset[str],
    settings: Any,
) -> frozenset[str]:
    gate = evaluate_knowledge_workspace_gate(settings)
    if gate.workspace_mode == _WORKSPACE_LOCAL:
        return capabilities
    if gate.cloud_formal_writes_allowed:
        return capabilities
    return frozenset(capabilities - FORMAL_CLOUD_WRITE_CAPABILITIES)


def assert_formal_cloud_write_allowed(
    *,
    settings: Any,
    capability: str,
    correlation_id: str | None = None,
) -> None:
    """Raise when a cloud-formal mutation is attempted without formal identity."""
    if capability not in FORMAL_CLOUD_WRITE_CAPABILITIES:
        return
    gate = evaluate_knowledge_workspace_gate(settings)
    if gate.workspace_mode == _WORKSPACE_LOCAL:
        return
    if gate.cloud_formal_writes_allowed:
        return
    raise KnowledgeBridgeError(
        code="KNOWLEDGE_CLOUD_FORMAL_WRITES_BLOCKED",
        message=(
            "雲端正式發布尚未開放：需 ENTRA 正式身分、關閉 relaxed／demo workflow，"
            "並啟用 AI_OPS_KNOWLEDGE_CLOUD_FORMAL_WRITES。"
            "地端測試請使用本機 sandbox 工作區。"
        ),
        status_code=403,
        correlation_id=correlation_id,
        details={
            "requiredCapability": capability,
            "knowledgeWorkspaceMode": gate.workspace_mode,
            "blockReasons": list(gate.block_reasons),
        },
    )


__all__ = [
    "FORMAL_CLOUD_WRITE_CAPABILITIES",
    "KnowledgeWorkspaceGate",
    "apply_knowledge_workspace_mode",
    "assert_formal_cloud_write_allowed",
    "can_switch_knowledge_workspace",
    "clear_knowledge_workspace_mode",
    "evaluate_knowledge_workspace_gate",
    "filter_knowledge_capabilities_for_workspace",
    "formal_identity_ready",
    "humanize_block_reasons",
    "load_persisted_knowledge_workspace_mode",
    "resolve_console_surface",
    "resolve_knowledge_workspace_mode",
    "resolve_knowledge_workspace_mode_source",
]
