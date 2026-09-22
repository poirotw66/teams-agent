"""Durable operator override for knowledge workspace mode.

Persists LOCAL_SANDBOX / CLOUD_FORMAL selection across Backoffice restarts
under the ops store tree. Loading an override never enables formal cloud
writes; those still require ``formal_identity_ready``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WORKSPACE_LOCAL = "LOCAL_SANDBOX"
_WORKSPACE_CLOUD = "CLOUD_FORMAL"
_ALLOWED = frozenset({_WORKSPACE_LOCAL, _WORKSPACE_CLOUD})
_SCHEMA_VERSION = 1


def knowledge_workspace_override_path(settings: Any) -> Path:
    """Return ``<ops>/knowledge_workspace.json`` beside the events store."""
    ops_store = Path(settings.ops_store_path)
    return ops_store.parent / "knowledge_workspace.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_knowledge_workspace_override(path: Path) -> dict[str, Any] | None:
    """Return override payload or None when absent/invalid."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Ignoring corrupt knowledge workspace override %s: %s", path, error)
        return None
    if not isinstance(payload, dict):
        return None
    mode = str(payload.get("overrideMode") or "").strip().upper()
    if mode not in _ALLOWED:
        return None
    return payload


def save_knowledge_workspace_override(
    path: Path,
    *,
    mode: str,
    actor_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Write override JSON. Does not touch formal-write flags."""
    normalized = str(mode or "").strip().upper()
    if normalized not in _ALLOWED:
        raise ValueError(
            "knowledgeWorkspaceMode must be LOCAL_SANDBOX or CLOUD_FORMAL."
        )
    payload = {
        "schemaVersion": _SCHEMA_VERSION,
        "overrideMode": normalized,
        "updatedAt": _utc_now_iso(),
        "updatedBy": actor_id,
        "reason": reason,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace so a crash mid-write cannot leave a half JSON that
    # would fail closed back to env on the next start.
    staging = path.with_suffix(path.suffix + ".tmp")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    staging.replace(path)
    return payload


def clear_knowledge_workspace_override(path: Path) -> bool:
    """Remove override file. Returns True when a file was deleted."""
    if not path.is_file():
        return False
    path.unlink()
    return True


def apply_persisted_workspace_override(settings: Any) -> str | None:
    """Load override from disk onto settings; return applied mode or None."""
    path = knowledge_workspace_override_path(settings)
    payload = load_knowledge_workspace_override(path)
    if payload is None:
        return None
    mode = str(payload["overrideMode"]).strip().upper()
    object.__setattr__(settings, "knowledge_workspace_mode", mode)
    object.__setattr__(settings, "knowledge_workspace_override_active", True)
    logger.info(
        "Loaded knowledge workspace override mode=%s from %s",
        mode,
        path,
    )
    return mode


__all__ = [
    "apply_persisted_workspace_override",
    "clear_knowledge_workspace_override",
    "knowledge_workspace_override_path",
    "load_knowledge_workspace_override",
    "save_knowledge_workspace_override",
]
